"""Step 2 of the continuous workflow: choose a time range and archive continuous data.

Qt port of ``seed_vault.ui.components.continuous_waveform.ContinuousComponents``.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSplitter,
                               QVBoxLayout, QWidget)

from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.qt.widgets import Banner, LogView, Section, UtcDateTimeEdit, button, hbox, to_py_datetime
from seed_vault.qt.workers import run_task_with_stop
from seed_vault.service.seismoloader import run_continuous
from seed_vault.service.settings_store import WORKFLOW_SECTIONS, refresh_sections, save_sections
from seed_vault.service.utils import get_time_interval, parse_inv, shift_time


class ContinuousPage(QWidget):
    def __init__(self, settings: SeismoLoaderSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._task = None
        self._build_ui()
        self.load_from_settings()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(6, 6, 6, 6)
        tr = Section("Time range")
        f = QFormLayout()
        self.start_edit, self.end_edit = UtcDateTimeEdit(), UtcDateTimeEdit()
        self.start_edit.dateTimeChanged.connect(self._validate)
        self.end_edit.dateTimeChanged.connect(self._validate)
        f.addRow("Start (UTC):", self.start_edit)
        f.addRow("End (UTC):", self.end_edit)
        tr.addLayout(f)

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Start</b>"), 0, 0, 1, 2, Qt.AlignCenter)
        grid.addWidget(QLabel("<b>End</b>"), 0, 2, 1, 2, Qt.AlignCenter)
        for r, unit in enumerate(("year", "month", "week", "day"), start=1):
            for c, (which, sign) in enumerate((("start", -1), ("start", 1), ("end", -1), ("end", 1))):
                b = button(f"{'−' if sign < 0 else '+'}{unit.title()}",
                           lambda _=False, w=which, u=unit, s=sign: self._shift(w, u, s))
                grid.addWidget(b, r, c)
        tr.addLayout(grid)
        tr.addLayout(hbox(*[button(lbl, lambda _=False, k=key: self._preset(k))
                            for lbl, key in (("Last Month", "month"), ("Last Week", "week"), ("Last Day", "day"))]))
        self.date_error = QLabel("End time must be after start time.")
        self.date_error.setStyleSheet("color: #b00020;")
        self.date_error.hide()
        tr.addWidget(self.date_error)
        sl.addWidget(tr)

        nslc = Section("Submitted NSLCs")
        self.nslc_label = QLabel()
        self.nslc_label.setWordWrap(True)
        self.nslc_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nslc.addWidget(self.nslc_label)
        sl.addWidget(nslc)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        split.addWidget(scroll)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(6, 0, 0, 0)
        title = QLabel("<h2>Continuous Waveform Archiving</h2>")
        self.get_btn = button("Download Waveforms", self.start, primary=True)
        self.cancel_btn = button("Cancel", self.cancel, "Stops after the current request finishes")
        self.cancel_btn.setEnabled(False)
        ml.addLayout(hbox(title, None, self.get_btn, self.cancel_btn))
        self.banner = Banner()
        ml.addWidget(self.banner)
        self.log = LogView()
        ml.addWidget(self.log, 1)
        split.addWidget(main)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 1000])

    # ------------------------------------------------------------------
    def load_from_settings(self):
        dc = self.settings.station.date_config
        self.start_edit.set_py(dc.start_time)
        self.end_edit.set_py(dc.end_time)
        self.refresh_nslc()
        self._validate()

    def refresh_nslc(self):
        nets, stas, locs, chas = parse_inv(self.settings.station.selected_invs)
        fmt = lambda xs: ", ".join(xs) if xs else "None"  # noqa: E731
        self.nslc_label.setText(
            f"<b>Networks:</b> {fmt(nets)}<br><b>Stations:</b> {fmt(stas)}<br>"
            f"<b>Locations:</b> {fmt([l if l else '--' for l in locs])}<br><b>Channels:</b> {fmt(chas)}")

    def _apply(self):
        self.settings.station.date_config.start_time = self.start_edit.py()
        self.settings.station.date_config.end_time = self.end_edit.py()

    def _validate(self, *_):
        ok = self.end_edit.py() > self.start_edit.py()
        self.date_error.setVisible(not ok)
        self.get_btn.setEnabled(ok and self._task is None)
        return ok

    def _shift(self, which, unit, sign):
        edit = self.start_edit if which == "start" else self.end_edit
        new = shift_time(edit.py(), unit, sign)
        edit.set_py(to_py_datetime(new))

    def _preset(self, key):
        end, start = get_time_interval(key)
        self.start_edit.set_py(start)
        self.end_edit.set_py(end)

    # ------------------------------------------------------------------
    def reset(self):
        self.cancel()
        self.log.clear_log()
        self.banner.hide()

    def start(self):
        if self._task is not None or not self._validate():
            return
        self._apply()
        try:
            save_sections(self.settings, WORKFLOW_SECTIONS)
            refresh_sections(self.settings)  # latest paths / credentials
        except Exception as e:  # noqa: BLE001
            print(f"Could not save settings: {e}")
        self.log.append_text("Running run_continuous\n-----------------------\n")
        self.banner.info("Downloading continuous waveforms… (this may take a long time)")
        self.get_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._task = run_task_with_stop(
            lambda stop: run_continuous(self.settings, stop),
            on_log=self.log.append_text, on_success=self._on_result,
            on_error=lambda m: self.banner.error(f"Download failed: {m}"), on_done=self._on_done)

    def cancel(self):
        if self._task is not None:
            self._task.cancel()
            self.cancel_btn.setEnabled(False)
            self.banner.warning("Cancelling download… (finishing the current request)")

    def _on_result(self, result):
        if self._task is not None and self._task.stop_event.is_set():
            self.banner.warning("Download was cancelled by user.")
        elif result:
            self.banner.success("Continuous data download completed successfully!")
        else:
            self.banner.warning("Download finished without data. Check the log for details.")

    def _on_done(self):
        self._task = None
        self.cancel_btn.setEnabled(False)
        self._validate()
