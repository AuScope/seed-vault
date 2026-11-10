"""Step 3 of the event/station workflows: download and view event arrivals.

Qt port of ``seed_vault.ui.components.waveform.WaveformComponents``.
"""
from typing import List

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from obspy import Stream, UTCDateTime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QRadioButton, QScrollArea, QSpinBox, QSplitter,
                               QTableView, QTabWidget, QVBoxLayout, QWidget)

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.qt.waveform_plot import TraceProcessor, plot_traces
from seed_vault.qt.widgets import Banner, DataFrameModel, LogView, Section, button, hbox
from seed_vault.qt.workers import run_task, run_task_with_stop
from seed_vault.service.seismoloader import run_event
from seed_vault.service.settings_store import WORKFLOW_SECTIONS, refresh_sections, save_sections
from seed_vault.service.utils import check_client_services

class WaveformCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas that lets the mouse wheel scroll the surrounding page.

    Ctrl + wheel zooms the (shared) time axis around the cursor instead.
    """

    def wheelEvent(self, event):
        if not (event.modifiers() & Qt.ControlModifier):
            # Matplotlib would swallow the wheel; hand it to the enclosing scroll area instead.
            area = self.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)
            else:
                event.ignore()
            return
        steps = event.angleDelta().y() / 120.0
        if not steps or not self.figure.axes:
            return
        pos = event.position()
        x_disp = pos.x() * self.device_pixel_ratio
        ax = self.figure.axes[0]
        x_data = ax.transData.inverted().transform((x_disp, 0))[0]
        lo, hi = ax.get_xlim()
        scale = 0.8 ** steps
        ax.set_xlim(x_data - (x_data - lo) * scale, x_data + (hi - x_data) * scale)
        self.draw_idle()
        event.accept()


ALL_NET, ALL_STA, ALL_CHA = "All networks", "All stations", "All channels"
EVENT_VIEW, STATION_VIEW = "Single event – multiple stations", "Single station – multiple events"


def _event_region(ev) -> str:
    try:
        return ev.extra.get("region", {}).get("value", "Unknown region")
    except Exception:
        return "Unknown region"


def _event_label(i, ev) -> str:
    mag = ev.magnitudes[0].mag if getattr(ev, "magnitudes", None) else 0.99
    return f"Event {i + 1}: {ev.origins[0].time} M{mag:.1f} {_event_region(ev)}"


class WaveformPage(QWidget):
    def __init__(self, settings: SeismoLoaderSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.stream: Stream = Stream()
        self.missing_data: dict = {}
        self.processor = TraceProcessor(settings)
        self._download = None
        self._plotting = False
        self._replot_pending = False
        self._building = False
        self.current_figure = None
        self._build_ui()
        self.load_from_settings()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(6, 6, 6, 6)

        src = Section("Data source")
        f = QFormLayout()
        self.min_radius, self.max_radius = QDoubleSpinBox(), QDoubleSpinBox()
        for w in (self.min_radius, self.max_radius):
            w.setMaximumWidth(90)
            w.setRange(0, 180)
            w.setSingleStep(0.5)
        f.addRow(QLabel("<b>Event–station distance</b>"))
        f.addRow("Radius (°):", hbox(self.min_radius, QLabel("to"), self.max_radius, None))
        f.addRow(QLabel("<b>Time window</b>"))
        self.before_p, self.after_p = QSpinBox(), QSpinBox()
        for w in (self.before_p, self.after_p):
            w.setMaximumWidth(90)
            w.setRange(0, 100000)
            w.setSingleStep(5)
            w.setSuffix(" s")
        self.before_p.setToolTip("Time window before P arrival")
        self.after_p.setToolTip("Time window after P arrival")
        self.before_p.valueChanged.connect(self._on_window_changed)
        self.after_p.valueChanged.connect(self._on_window_changed)
        f.addRow("Before P:", hbox(self.before_p, None))
        f.addRow("After P:", hbox(self.after_p, None))
        self.client_combo = QComboBox()
        self.client_combo.currentTextChanged.connect(self._on_client_changed)
        f.addRow("Client:", self.client_combo)
        self.client_warning = QLabel()
        self.client_warning.setWordWrap(True)
        self.client_warning.setStyleSheet("color: #a15c00;")
        self.client_warning.hide()
        f.addRow(self.client_warning)
        f.addRow(QLabel("<b>Download preferences</b>"))
        self.channel_pref = QLineEdit()
        self.channel_pref.setToolTip("Order of preferred channels (e.g. HH,BH,EH). Only the first existing "
                                     "channel in this list will be downloaded.")
        self.location_pref = QLineEdit()
        self.location_pref.setToolTip("Order of preferred location codes (e.g. 00,--,10,20). Only the first "
                                      "existing location code is downloaded. Use -- for a blank location.")
        for w in (self.channel_pref, self.location_pref):
            w.setMaximumWidth(170)
        f.addRow("Channel priority:", hbox(self.channel_pref, None))
        f.addRow("Location priority:", hbox(self.location_pref, None))
        self.pref_error = QLabel()
        self.pref_error.setStyleSheet("color: #b00020;")
        self.pref_error.setWordWrap(True)
        self.pref_error.hide()
        f.addRow(self.pref_error)
        self.force_redownload = QCheckBox("Force re-download")
        self.force_redownload.setToolTip("If off, data already available locally is not downloaded again.")
        f.addRow(self.force_redownload)
        src.addLayout(f)
        self.get_btn = button("Get Waveforms", self.start_download, primary=True)
        self.cancel_btn = button("Cancel", self.cancel_download, "Stops after the current request finishes")
        self.cancel_btn.setEnabled(False)
        src.addLayout(hbox(self.get_btn, self.cancel_btn))
        sl.addWidget(src)

        disp = Section("Display")
        g = QFormLayout()
        self.view_event = QRadioButton(EVENT_VIEW)
        self.view_station = QRadioButton(STATION_VIEW)
        self.view_event.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.view_event)
        grp.addButton(self.view_station)
        self.view_event.toggled.connect(self._on_view_type_changed)
        g.addRow(self.view_event)
        g.addRow(self.view_station)
        self.item_combo = QComboBox()
        self.item_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.item_combo.setMinimumContentsLength(20)
        self.item_combo.currentIndexChanged.connect(self._on_filters_changed)
        self.item_label = QLabel("Event:")
        g.addRow(self.item_label, self.item_combo)
        self.net_combo, self.sta_combo, self.cha_combo = QComboBox(), QComboBox(), QComboBox()
        for c in (self.net_combo, self.sta_combo, self.cha_combo):
            c.currentIndexChanged.connect(self._on_filters_changed)
        g.addRow("Network:", self.net_combo)
        g.addRow("Station:", self.sta_combo)
        g.addRow("Channel:", self.cha_combo)
        self.display_form = g
        self.per_page = QComboBox()
        self.per_page.addItems(["10", "25", "50"])
        self.per_page.setCurrentText("25")
        self.per_page.currentIndexChanged.connect(self._on_filters_changed)
        g.addRow("Traces per page:", hbox(self.per_page, None))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(self._on_page_changed)
        self.page_total = QLabel("/ 1")
        g.addRow("Page:", hbox(self.page_spin, self.page_total, None))
        self.total_label = QLabel()
        g.addRow(self.total_label)
        disp.addLayout(g)
        disp.addLayout(hbox(button("Reset filters", self.reset_filters),
                            button("Save PNG…", self.save_png)))
        sl.addWidget(disp)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        self.sidebar_display = disp
        split.addWidget(scroll)

        # ---- main tabs
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        self.banner = Banner()
        ml.addWidget(self.banner)
        self.tabs = QTabWidget()
        ml.addWidget(self.tabs, 1)

        plot_tab = QWidget()
        pl = QVBoxLayout(plot_tab)
        pl.setContentsMargins(0, 0, 0, 0)
        self.plot_status = QLabel("No waveforms yet. Use <b>Get Waveforms</b> to download event arrivals.")
        self.plot_status.setAlignment(Qt.AlignCenter)
        pl.addWidget(self.plot_status)
        self.toolbar_holder = QVBoxLayout()
        pl.addLayout(self.toolbar_holder)
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        pl.addWidget(self.plot_scroll, 1)
        self.tabs.addTab(plot_tab, "📊 Waveforms")

        self.log = LogView()
        self.tabs.addTab(self.log, "📝 Log")

        self.missing_model = DataFrameModel()
        mt = QTableView()
        mt.setModel(self.missing_model)
        mt.horizontalHeader().setStretchLastSection(True)
        mt.setWordWrap(True)
        self.missing_table = mt
        self.tabs.addTab(mt, "Missing data")
        split.addWidget(main)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 1000])

    # ------------------------------------------------------------------
    def load_from_settings(self):
        self._building = True
        s = self.settings
        self.min_radius.setValue(s.event.min_radius or 0.0)
        self.max_radius.setValue(s.event.max_radius or 90.0)
        self.before_p.setValue(int(s.event.before_p_sec or 20))
        self.after_p.setValue(int(s.event.after_p_sec or 100))
        clients = list(s.client_url_mapping.get_clients())
        self.client_combo.clear()
        self.client_combo.addItems(clients)
        if s.waveform.client in clients:
            self.client_combo.setCurrentText(s.waveform.client)
        self.channel_pref.setText(s.waveform.channel_pref or "")
        self.location_pref.setText(s.waveform.location_pref or "")
        self.force_redownload.setChecked(bool(s.waveform.force_redownload))
        self._building = False

    def apply_widgets_to_settings(self) -> bool:
        s = self.settings
        s.event.min_radius = self.min_radius.value()
        s.event.max_radius = self.max_radius.value()
        s.event.before_p_sec = self.before_p.value()
        s.event.after_p_sec = self.after_p.value()
        s.waveform.client = self.client_combo.currentText() or s.waveform.client
        s.waveform.force_redownload = self.force_redownload.isChecked()
        errors = []
        cp = self.channel_pref.text().replace(" ", "").upper()
        if cp:
            if all(len(c) == 2 for c in cp.split(",")):
                s.waveform.channel_pref = cp
            else:
                errors.append("Invalid channel priority: each code must be 2 characters (e.g. HH,BH,EH).")
        lp = self.location_pref.text().replace(" ", "")
        if lp:
            if all(len(c) <= 2 for c in lp.split(",")):
                s.waveform.location_pref = lp
            else:
                errors.append("Invalid location priority: each code must be 0–2 characters (e.g. 00,--,10).")
        self.pref_error.setText("<br>".join(errors))
        self.pref_error.setVisible(bool(errors))
        return not errors

    def _on_client_changed(self, name):
        if self._building or not name:
            return
        self.client_warning.hide()

        def done(services):
            if self.client_combo.currentText() == name and not (services or {}).get("dataselect"):
                self.client_warning.setText(f"⚠️ Client '{name}' does not appear to support the WAVEFORM "
                                            "(dataselect) service.")
                self.client_warning.show()
        run_task(check_client_services, name, on_success=done, capture_output=False)

    def _on_window_changed(self, *_):
        if self._building:
            return
        self.settings.event.before_p_sec = self.before_p.value()
        self.settings.event.after_p_sec = self.after_p.value()
        self.processor.clear()
        self.request_replot()

    # ------------------------------------------------------------------
    # download
    # ------------------------------------------------------------------
    def reset(self):
        """Called when the user navigates back: forget results and logs."""
        self.cancel_download()
        self.stream, self.missing_data = Stream(), {}
        self.processor.clear()
        self.log.clear_log()
        self.banner.hide()
        self._set_figure(None)
        self.plot_status.setText("No waveforms yet. Use <b>Get Waveforms</b> to download event arrivals.")
        self.plot_status.show()
        self.missing_model.set_dataframe(pd.DataFrame())
        self._populate_selectors()

    def start_download(self):
        if self._download is not None:
            return
        if not self.settings.event.selected_catalogs or not self.settings.station.selected_invs:
            self.banner.warning("Please select events and stations before downloading waveforms.")
            return
        if not self.apply_widgets_to_settings():
            return
        try:
            save_sections(self.settings, WORKFLOW_SECTIONS)
            refresh_sections(self.settings)  # latest paths / credentials
        except Exception as e:  # noqa: BLE001
            print(f"Could not save settings: {e}")
        self.log.append_text("Running run_event\n-----------------\n")
        self.tabs.setCurrentWidget(self.log)
        self.banner.info("Downloading waveforms… (this may take several minutes)")
        self._lock_source(True)
        self.cancel_btn.setEnabled(True)
        self.processor.clear()
        self._download = run_task_with_stop(
            lambda stop: run_event(self.settings, stop),
            on_log=self.log.append_text, on_success=self._on_download_result,
            on_error=lambda m: self.banner.error(f"Download failed: {m}"),
            on_done=self._on_download_done)

    def _lock_source(self, locked: bool):
        """The backend reads these settings while downloading; don't let them change underneath it."""
        for w in (self.min_radius, self.max_radius, self.before_p, self.after_p, self.client_combo,
                  self.channel_pref, self.location_pref, self.force_redownload, self.get_btn):
            w.setEnabled(not locked)

    def cancel_download(self):
        if self._download is not None:
            self._download.cancel()
            self.banner.warning("Cancelling download… (finishing the current request)")
            self.cancel_btn.setEnabled(False)

    def _on_download_done(self):
        cancelled = self._download is not None and self._download.stop_event.is_set()
        self._download = None
        self._lock_source(False)
        self.cancel_btn.setEnabled(False)
        if cancelled:
            self.banner.warning("Waveform download cancelled.")

    def _on_download_result(self, result):
        if result and not (self._download and self._download.stop_event.is_set()):
            self.stream, self.missing_data = result
            if self.stream:
                self.banner.success(f"Retrieved waveforms for {len(self.stream)} channels.")
                self.tabs.setCurrentIndex(0)
            else:
                self.banner.warning("No waveforms retrieved. Check your selection criteria and the log.")
        elif not (self._download and self._download.stop_event.is_set()):
            self.banner.warning("No waveforms retrieved. Check your selection criteria and the log.")
        self._populate_selectors()
        self._fill_missing_table()
        self.request_replot()

    # ------------------------------------------------------------------
    # display filters
    # ------------------------------------------------------------------
    def _valid_events(self):
        events = self.settings.event.selected_catalogs or []
        have = {str(getattr(tr.stats, "resource_id", "")) for tr in self.stream}
        return [(i, ev) for i, ev in enumerate(events) if str(ev.resource_id) in have]

    def _populate_selectors(self):
        self._building = True
        try:
            self.item_combo.clear()
            if self.view_event.isChecked():
                self.item_label.setText("Event:")
                for i, ev in self._valid_events():
                    self.item_combo.addItem(_event_label(i, ev), str(ev.resource_id))
            else:
                self.item_label.setText("Station:")
                for code in sorted({f"{tr.stats.network}.{tr.stats.station}" for tr in self.stream}):
                    self.item_combo.addItem(code, code)
            nets = sorted({tr.stats.network for tr in self.stream})
            stas = sorted({tr.stats.station for tr in self.stream})
            chas = sorted({tr.stats.channel for tr in self.stream})
            for combo, first, items in ((self.net_combo, ALL_NET, nets), (self.sta_combo, ALL_STA, stas),
                                        (self.cha_combo, ALL_CHA, chas)):
                cur = combo.currentText()
                combo.clear()
                combo.addItems([first] + items)
                if cur in items:
                    combo.setCurrentText(cur)
            self.total_label.setText(f"Total traces: {len(self.stream)}" if self.stream else "")
        finally:
            self._building = False

    def reset_filters(self):
        self._building = True
        self.net_combo.setCurrentIndex(0)
        self.sta_combo.setCurrentIndex(0)
        self.cha_combo.setCurrentIndex(0)
        self.per_page.setCurrentText("25")
        self._building = False
        self._on_filters_changed()

    def _on_view_type_changed(self, *_):
        event_view = self.view_event.isChecked()
        self.display_form.setRowVisible(self.net_combo, event_view)
        self.display_form.setRowVisible(self.sta_combo, event_view)
        self._populate_selectors()
        self._on_filters_changed()

    def _on_filters_changed(self, *_):
        if self._building:
            return
        self._building = True
        self.page_spin.setValue(1)
        self._building = False
        self.request_replot()

    def _on_page_changed(self, *_):
        if not self._building:
            self.request_replot()

    def _filtered_stream(self) -> Stream:
        st = self.stream
        if not st:
            return Stream()
        key = self.item_combo.currentData()
        if self.view_event.isChecked():
            st = Stream([tr for tr in st if str(getattr(tr.stats, "resource_id", "")) == key]) if key else Stream()
            st = st.copy()
            try:
                st.merge(method=0, fill_value="interpolate")
            except Exception:
                pass
        else:
            if not key:
                return Stream()
            net, sta = key.split(".", 1)
            st = st.select(network=net, station=sta)
        cha = self.cha_combo.currentText()
        if self.view_event.isChecked():
            net, sta = self.net_combo.currentText(), self.sta_combo.currentText()
        else:  # the station selector already fixes network & station
            net, sta = ALL_NET, ALL_STA
        out = Stream([tr for tr in st
                      if (net in (ALL_NET, "") or tr.stats.network == net)
                      and (sta in (ALL_STA, "") or tr.stats.station == sta)
                      and (cha in (ALL_CHA, "") or tr.stats.channel == cha)])
        if self.view_event.isChecked():
            out.traces.sort(key=lambda tr: (getattr(tr.stats, "distance_km", 1e9) or 1e9, tr.id))
        else:
            out.traces.sort(key=lambda tr: getattr(tr.stats, "distance_km", 1e9) or 1e9)
        return out

    # ------------------------------------------------------------------
    # plotting (processing runs off the GUI thread)
    # ------------------------------------------------------------------
    def request_replot(self):
        if self._plotting:
            self._replot_pending = True
            return
        st = self._filtered_stream()
        per = int(self.per_page.currentText())
        pages = max(1, (len(st) - 1) // per + 1) if st else 1
        self._building = True
        self.page_spin.setMaximum(pages)
        self._building = False
        self.page_total.setText(f"/ {pages}")
        if not st:
            self._set_figure(None)
            if self.stream:
                self.plot_status.setText("No waveforms match the current filter criteria.")
                self.plot_status.show()
            return
        page = self.page_spin.value() - 1
        chunk = Stream(st.traces[page * per:(page + 1) * per])
        mode = "event" if self.view_event.isChecked() else "station"
        self._plotting = True
        self.plot_status.setText("Plotting…")
        self.plot_status.show()
        run_task(plot_traces, chunk, self.settings, self.processor, mode,
                 on_success=self._set_figure,
                 on_error=lambda m: self.banner.error(f"Plotting failed: {m}"),
                 on_done=self._on_plot_done, capture_output=False)

    def _on_plot_done(self):
        self._plotting = False
        if self._replot_pending:
            self._replot_pending = False
            self.request_replot()

    def _set_figure(self, fig):
        while self.toolbar_holder.count():
            w = self.toolbar_holder.takeAt(0).widget()
            if w:
                w.deleteLater()
        old = self.plot_scroll.takeWidget()
        if old:
            old.deleteLater()
        self.current_figure = fig
        if fig is None:
            return
        canvas = WaveformCanvas(fig)
        w_in, h_in = fig.get_size_inches()
        canvas.setMinimumHeight(int(h_in * fig.dpi * 0.85))
        self.plot_scroll.setWidget(canvas)
        self.toolbar_holder.addWidget(NavigationToolbar2QT(canvas, self))
        self.plot_status.hide()
        canvas.draw_idle()

    def save_png(self):
        if self.current_figure is None:
            return self.banner.warning("Nothing to save yet.")
        path, _ = QFileDialog.getSaveFileName(self, "Save plot", "waveform_plot.png", "PNG (*.png);;PDF (*.pdf)")
        if path:
            self.current_figure.savefig(path, dpi=300, bbox_inches="tight")
            self.banner.success(f"Saved {path}")

    # ------------------------------------------------------------------
    # missing data
    # ------------------------------------------------------------------
    def _fill_missing_table(self):
        rows = []
        try:
            catalog = self.settings.event.selected_catalogs.copy()
            catalog.events.sort(key=lambda x: x.origins[0].time if x.origins else UTCDateTime(0))
        except Exception:
            catalog = self.settings.event.selected_catalogs or []
        for ev in catalog:
            rid = str(ev.resource_id)
            entry = (self.missing_data or {}).get(rid)
            if not entry:
                continue
            missing: List[str] = []
            for sta_key, val in entry.items():
                if val == "ALL":
                    missing.append(f"{sta_key}.*")
                elif isinstance(val, list):
                    missing.extend(val)
            if missing:
                mag = ev.magnitudes[0].mag if ev.magnitudes else float("nan")
                rows.append({"Event": f"{ev.origins[0].time.strftime('%Y-%m-%d %H:%M:%S')}, M{mag:.1f}, "
                                      f"{_event_region(ev)}",
                             "Missing data": ", ".join(missing), "Resource ID": rid})
        df = pd.DataFrame(rows)
        self.missing_model.set_dataframe(df)
        self.missing_table.resizeColumnsToContents()
        self.tabs.setTabText(2, f"Missing data ({len(df)})" if len(df) else "Missing data")
