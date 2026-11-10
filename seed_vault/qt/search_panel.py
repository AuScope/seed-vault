"""Search & select events or stations: filters + map + table.

Qt port of ``seed_vault.ui.components.base.BaseComponent``. One instance is
created per workflow step; the workflow page decides which step comes first.
"""
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from obspy.core.event import Catalog, read_events
from obspy.core.inventory import Inventory, read_inventory
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QProgressBar, QScrollArea, QSplitter, QTableView,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from seed_vault.enums.config import GeoConstraintType, Levels
from seed_vault.enums.ui import Steps
from seed_vault.models.common import CircleArea, RectangleArea
from seed_vault.models.config import GeometryConstraint, SeismoLoaderSettings
from seed_vault.qt.map_widget import MapWidget, build_markers, build_prev_markers
from seed_vault.qt.widgets import (Banner, DataFrameModel, FilterProxy, Section, UtcDateTimeEdit, button,
                                   hbox)
from seed_vault.qt.workers import run_task
from seed_vault.service.events import event_response_to_df, get_event_data
from seed_vault.service.settings_store import WORKFLOW_SECTIONS, save_sections
from seed_vault.service.stations import get_station_data, inventory_to_bibtex, station_response_to_df
from seed_vault.service.utils import check_client_services, get_time_interval
from seed_vault.utils.geo import is_valid_circle, is_valid_rectangle, unique_geo_constraints

HTTP_ERRORS = {
    204: "No data found",
    400: "Malformed input or unrecognized search parameter",
    401: "Unauthorized access",
    403: "Authentication failed for restricted data",
    413: "Data request is too large for server; try reducing size into several pieces",
    502: "Server response is invalid; please try again another time",
    503: "Server appears to be down; please try again another time",
    504: "Server appears to be down; please try again another time",
}
SEL = "is_selected"
MAX_PREV_FOR_AREA = 50   # cap on 'search around previous selection' circles


def friendly_error(msg: str) -> str:
    if "TimeoutError" in msg or "timed out" in msg.lower():
        return "Server timeout, try again in a minute."
    m = re.search(r"\b(\d{3})\b", msg)
    code = int(m.group(1)) if m else None
    friendly = HTTP_ERRORS.get(code, "An unexpected error occurred. Please try again.")
    return f"⚠️ {friendly}" + (f"<br><small>Error {code}: {msg}</small>" if code else f"<br><small>{msg}</small>")


class SearchPanel(QWidget):
    """Search, view and select events (``Steps.EVENT``) or stations (``Steps.STATION``)."""

    selectionChanged = Signal(int)      # number of selected rows
    busyChanged = Signal(bool)

    def __init__(self, settings: SeismoLoaderSettings, step: Steps, prev_step: Optional[Steps] = None,
                 stage: int = 1, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.step = step
        self.prev_step = prev_step
        self.stage = stage
        self.noun = "event" if step == Steps.EVENT else "station"
        self.df = pd.DataFrame()
        self.catalogs = Catalog()
        self.inventories = Inventory()
        self.df_prev = pd.DataFrame()
        self.dates_manually_set = False
        self._task = None
        self._building = False

        self._build_ui()
        self.load_from_settings(initial=True)

    # ------------------------------------------------------------------
    # config accessors
    # ------------------------------------------------------------------
    @property
    def cfg(self):
        return self.settings.event if self.step == Steps.EVENT else self.settings.station

    def geo(self) -> List[GeometryConstraint]:
        return list(self.cfg.geo_constraint or [])

    def set_geo(self, constraints: List[GeometryConstraint]):
        self.cfg.geo_constraint = unique_geo_constraints(constraints)
        self.map.set_areas(self.cfg.geo_constraint)
        self._fill_area_tables()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # ---- sidebar
        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(6, 6, 6, 6)
        side_lay.addWidget(self._build_filters())
        side_lay.addWidget(self._build_area_editor())
        if self.prev_step is not None:
            side_lay.addWidget(self._build_search_around())
        side_lay.addWidget(self._build_import_export())
        side_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(400)
        self.sidebar = side
        split.addWidget(scroll)

        # ---- main: banner + map / table
        main = QWidget()
        mlay = QVBoxLayout(main)
        mlay.setContentsMargins(0, 0, 0, 0)
        self.banner = Banner()
        mlay.addWidget(self.banner)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        mlay.addWidget(self.progress)

        vsplit = QSplitter(Qt.Vertical)
        self.map = MapWidget()
        self.map.drawCreated.connect(self._on_draw_created)
        self.map.markerClicked.connect(self._on_marker_clicked)
        hint = QLabel(f"Draw a rectangle or circle (tools at top-left) to search {self.noun}s in an area. "
                      f"Click a marker to toggle its selection." +
                      (" Marker size reflects magnitude." if self.step == Steps.EVENT else ""))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        map_box = QWidget()
        ml = QVBoxLayout(map_box)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(hint)
        ml.addWidget(self.map, 1)
        vsplit.addWidget(map_box)
        vsplit.addWidget(self._build_table())
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        vsplit.setSizes([560, 340])
        mlay.addWidget(vsplit, 1)
        split.addWidget(main)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 1000])

    def _build_filters(self) -> QWidget:
        sec = Section("Filters")
        form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setEditable(False)
        self.client_combo.currentTextChanged.connect(self._on_client_changed)
        form.addRow("Client:", self.client_combo)
        self.client_warning = QLabel()
        self.client_warning.setWordWrap(True)
        self.client_warning.setStyleSheet("color: #a15c00;")
        self.client_warning.hide()
        form.addRow(self.client_warning)

        presets = (("Last Month", "month"), ("Last Week", "week"), ("Last Day", "day")) \
            if self.step == Steps.EVENT else (("Last Year", "year"), ("Last Month", "month"), ("Last Week", "week"))
        form.addRow(hbox(*[button(label, lambda _=False, k=key: self._apply_preset(k)) for label, key in presets]))

        self.start_edit = UtcDateTimeEdit()
        self.end_edit = UtcDateTimeEdit()
        for w in (self.start_edit, self.end_edit):
            w.dateTimeChanged.connect(self._on_dates_edited)
        form.addRow("Start (UTC):", self.start_edit)
        form.addRow("End (UTC):", self.end_edit)
        self.date_error = QLabel("End must be after start.")
        self.date_error.setStyleSheet("color: #b00020;")
        self.date_error.hide()
        form.addRow(self.date_error)

        if self.step == Steps.EVENT:
            self.min_mag, self.max_mag = self._range_spin(-2.0, 10.0, 0.1, 1)
            self.min_depth, self.max_depth = self._range_spin(-5.0, 1000.0, 1.0, 0)
            form.addRow("Magnitude:", hbox(self.min_mag, QLabel("to"), self.max_mag, None))
            form.addRow("Depth (km):", hbox(self.min_depth, QLabel("to"), self.max_depth, None))
        else:
            self.net_edit, self.sta_edit = QLineEdit(), QLineEdit()
            self.loc_edit, self.cha_edit = QLineEdit(), QLineEdit()
            for w, tip in ((self.net_edit, "e.g. IU,II or *"), (self.sta_edit, "e.g. ANMO or *"),
                           (self.loc_edit, "e.g. 00,-- or *"), (self.cha_edit, "e.g. ?H?,?N?")):
                w.setPlaceholderText(tip)
            grid = QGridLayout()
            for i, (lbl, w) in enumerate((("Network", self.net_edit), ("Station", self.sta_edit),
                                          ("Location", self.loc_edit), ("Channel", self.cha_edit))):
                grid.addWidget(QLabel(lbl), 0, i)
                grid.addWidget(w, 1, i)
            form.addRow(grid)
            self.highest_sr = QCheckBox("Highest sample rate only")
            self.highest_sr.setToolTip("If a station has multiple channels for the same component (e.g. HHZ & "
                                       "LHZ), only select the one with the highest sample rate (HHZ).")
            self.restricted = QCheckBox("Include restricted data")
            self.response = QCheckBox("Include instrument response")
            self.response.setToolTip("Download station metadata with full instrument response. Potentially makes "
                                     "the download much larger. Use only if you need to export StationXML or plot "
                                     "with response removed.")
            for w in (self.highest_sr, self.restricted, self.response):
                form.addRow(w)

        self.search_btn = button(f"Search {self.noun.title()}s", self.search, primary=True)
        self.clear_btn = button("Clear All", self.clear_all, f"Remove all {self.noun}s and drawn areas")
        form.addRow(hbox(self.search_btn, self.clear_btn))
        self.auto_search = QCheckBox("Search automatically after drawing an area")
        self.auto_search.setChecked(True)
        form.addRow(self.auto_search)
        sec.addLayout(form)
        return sec

    def _range_spin(self, lo, hi, step, decimals):
        a, b = QDoubleSpinBox(), QDoubleSpinBox()
        for w in (a, b):
            w.setMaximumWidth(90)
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setDecimals(decimals)
        return a, b

    def _build_area_editor(self) -> QWidget:
        sec = Section("Search areas", expanded=False)
        sec.addWidget(QLabel("Rectangles (longitude 0–360):"))
        self.rect_table = self._area_table(["min_lat", "max_lat", "min_lon", "max_lon"])
        sec.addWidget(self.rect_table)
        sec.addWidget(QLabel("Circles (radii in degrees):"))
        self.circ_table = self._area_table(["lat", "lon", "min_radius", "max_radius"])
        sec.addWidget(self.circ_table)
        self.area_msg = QLabel()
        self.area_msg.setWordWrap(True)
        self.area_msg.setStyleSheet("color: #b00020;")
        sec.addWidget(self.area_msg)
        sec.addLayout(hbox(button("Add rectangle", lambda: self._add_area_row(self.rect_table, [-10, 10, 170, 190])),
                           button("Add circle", lambda: self._add_area_row(self.circ_table, [0, 180, 0, 10]))))
        sec.addLayout(hbox(button("Apply edits", self._apply_area_tables),
                           button("Delete highlighted", self._delete_area_rows),
                           button("Clear areas", lambda: self.set_geo([]))))
        return sec

    def _area_table(self, cols) -> QTableWidget:
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.verticalHeader().hide()
        t.setMaximumHeight(120)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        return t

    def _build_search_around(self) -> QWidget:
        prev_noun = "event" if self.prev_step == Steps.EVENT else "station"
        sec = Section(f"Search around selected {prev_noun}s")
        sec.addWidget(QLabel(f"Draw a ring around each selected {prev_noun} and search {self.noun}s inside it."))
        self.around_min, self.around_max = self._range_spin(0.0, 180.0, 0.5, 2)
        f = QFormLayout()
        f.addRow("Radius (°):", hbox(self.around_min, QLabel("to"), self.around_max, None))
        sec.addLayout(f)
        self.around_btn = button("Draw area", self._draw_area_around_prev)
        self.around_msg = QLabel()
        self.around_msg.setWordWrap(True)
        sec.addLayout(hbox(self.around_btn, None))
        sec.addWidget(self.around_msg)
        return sec

    def _build_import_export(self) -> QWidget:
        sec = Section("Import / Export", expanded=False)
        self.export_selected_only = QCheckBox("Export selected only")
        sec.addWidget(self.export_selected_only)
        row = [button("CSV", self.export_csv, f"Export {self.noun} table to CSV")]
        if self.step == Steps.EVENT:
            row += [button("QuakeML", self.export_xml, "Export catalog to QuakeML"),
                    button("KML", self.export_txt, "Export catalog to KML")]
        else:
            row += [button("StationXML", self.export_xml, "Export station metadata to FDSN StationXML"),
                    button("Text", self.export_txt, "Export station metadata as FDSN text"),
                    button("BibTeX", self.export_bibtex, "Export network citations to BibTeX")]
        sec.addLayout(hbox(*row))
        sec.addLayout(hbox(button("Import file…", self.import_file,
                                  "Import QuakeML / StationXML results, or a .cfg search configuration"), None))
        return sec

    def _build_table(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        if self.step == Steps.EVENT:
            headers = {"time": "time (UTC)", "magnitude": "mag", "magnitude type": "mag type",
                       "latitude": "lat", "longitude": "lon", "place": "location"}
            fmts = {"magnitude": "{:.1f}", "depth (km)": "{:.1f}", "latitude": "{:.4f}", "longitude": "{:.4f}",
                    "time": "%Y-%m-%d %H:%M:%S"}
        else:
            headers = {"network": "net", "station": "sta", "latitude": "lat", "longitude": "lon",
                       "elevation": "elev", "loc. codes": "loc", "channels": "cha",
                       "start date (UTC)": "start", "end date (UTC)": "end"}
            fmts = {"latitude": "{:.4f}", "longitude": "{:.4f}", "elevation": "{:.0f}"}
        self.model = DataFrameModel(check_col=SEL, hidden=("detail",), headers=headers, formats=fmts)
        self.model.selection_changed.connect(self._on_model_selection_changed)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        # Don't re-sort when a row is (un)checked – rows would jump around under the cursor.
        self.proxy.setDynamicSortFilter(False)

        self.count_label = QLabel(f"No {self.noun}s loaded")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_text)
        lay.addLayout(hbox(self.count_label, None, self.filter_edit,
                           button("Select all", lambda: self._check_rows(True, visible_only=True),
                                  "Select all rows currently shown"),
                           button("Unselect all", lambda: self._check_rows(False, visible_only=False)),
                           button("Select highlighted", lambda: self._check_highlighted(True)),
                           button("Unselect highlighted", lambda: self._check_highlighted(False)),
                           button("Zoom to results", self.map.fit_markers)))

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self._user_sorted = False
        self.table.horizontalHeader().sectionClicked.connect(lambda _c: setattr(self, "_user_sorted", True))
        lay.addWidget(self.table, 1)
        return box

    # ------------------------------------------------------------------
    # settings <-> widgets
    # ------------------------------------------------------------------
    def load_from_settings(self, initial: bool = False):
        """Populate widgets from ``self.settings``."""
        self._building = True
        try:
            clients = list(self.settings.client_url_mapping.get_clients())
            self.client_combo.clear()
            self.client_combo.addItems(clients)
            if self.cfg.client in clients:
                self.client_combo.setCurrentText(self.cfg.client)

            if initial and self.prev_step is None:
                # fresh search: default window (same as the original app)
                has_sel = (self.settings.event.selected_catalogs if self.step == Steps.EVENT
                           else self.settings.station.selected_invs)
                if not has_sel:
                    end, start = get_time_interval("month" if self.step == Steps.EVENT else "year")
                    self.cfg.date_config.start_time, self.cfg.date_config.end_time = start, end
            self.start_edit.set_py(self.cfg.date_config.start_time)
            self.end_edit.set_py(self.cfg.date_config.end_time)

            if self.step == Steps.EVENT:
                e = self.settings.event
                self.min_mag.setValue(e.min_magnitude)
                self.max_mag.setValue(e.max_magnitude)
                self.min_depth.setValue(e.min_depth)
                self.max_depth.setValue(e.max_depth)
            else:
                s = self.settings.station
                self.net_edit.setText(s.network or "")
                self.sta_edit.setText(s.station or "")
                self.loc_edit.setText(s.location or "")
                self.cha_edit.setText(s.channel or "")
                self.highest_sr.setChecked(bool(s.highest_samplerate_only))
                self.restricted.setChecked(bool(s.include_restricted))
                self.response.setChecked(s.level == Levels.RESPONSE)
            if self.prev_step is not None:
                self.around_min.setValue(self.settings.event.min_radius or 0.0)
                self.around_max.setValue(self.settings.event.max_radius or 0.0)
        finally:
            self._building = False
        self.map.set_areas(self.geo())
        self._fill_area_tables()
        self._validate_dates()

    def apply_widgets_to_settings(self):
        self.cfg.client = self.client_combo.currentText() or self.cfg.client
        self.cfg.date_config.start_time = self.start_edit.py()
        self.cfg.date_config.end_time = self.end_edit.py()
        if self.step == Steps.EVENT:
            e = self.settings.event
            e.min_magnitude, e.max_magnitude = sorted((self.min_mag.value(), self.max_mag.value()))
            e.min_depth, e.max_depth = sorted((self.min_depth.value(), self.max_depth.value()))
        else:
            s = self.settings.station
            s.network = self.net_edit.text().strip() or "*"
            s.station = self.sta_edit.text().strip() or "*"
            s.location = self.loc_edit.text().strip() or "*"
            s.channel = self.cha_edit.text().strip() or "*"
            s.highest_samplerate_only = self.highest_sr.isChecked()
            s.include_restricted = self.restricted.isChecked()
            s.level = Levels.RESPONSE if self.response.isChecked() else Levels.CHANNEL
        if self.prev_step is not None:
            self.settings.event.min_radius = self.around_min.value()
            self.settings.event.max_radius = self.around_max.value()

    def persist(self):
        """Save filter settings so they survive restarts (mirrors the original auto-save)."""
        try:
            self.apply_widgets_to_settings()
            save_sections(self.settings, WORKFLOW_SECTIONS)
        except Exception as e:  # noqa: BLE001
            print(f"Could not save settings: {e}")

    # ------------------------------------------------------------------
    # dates
    # ------------------------------------------------------------------
    def _apply_preset(self, key):
        end, start = get_time_interval(key)
        self._building = True
        self.start_edit.set_py(start)
        self.end_edit.set_py(end)
        self._building = False
        self.dates_manually_set = True
        self._validate_dates()

    def _on_dates_edited(self, *_):
        if not self._building:
            self.dates_manually_set = True
        self._validate_dates()

    def _validate_dates(self) -> bool:
        ok = self.end_edit.py() > self.start_edit.py()
        self.date_error.setVisible(not ok)
        self.search_btn.setEnabled(ok and self._task is None)
        return ok

    def sync_dates_from_previous_step(self):
        """When entering step 2, derive a sensible date window from step-1 selections."""
        if self.dates_manually_set:
            return
        start = end = None
        if self.prev_step == Steps.EVENT and self.settings.event.selected_catalogs:
            times = [(ev.preferred_origin() or ev.origins[0]).time for ev in self.settings.event.selected_catalogs
                     if ev.origins]
            if times:
                start, end = min(times).datetime, (max(times) + 86400).datetime
        elif self.prev_step == Steps.STATION and self.settings.station.selected_invs:
            starts, ends = [], []
            for net in self.settings.station.selected_invs:
                for sta in net:
                    if sta.start_date:
                        starts.append(sta.start_date.datetime)
                    ends.append(sta.end_date.datetime if sta.end_date else datetime.now(timezone.utc).replace(tzinfo=None))
            if starts:
                start, end = min(starts), max(ends)
        if start and end:
            self.cfg.date_config.start_time, self.cfg.date_config.end_time = start, end
            self._building = True
            self.start_edit.set_py(start)
            self.end_edit.set_py(end)
            self._building = False
            self._validate_dates()

    # ------------------------------------------------------------------
    # client service check (network call -> background)
    # ------------------------------------------------------------------
    def _on_client_changed(self, name):
        if self._building or not name:
            return
        self.client_warning.hide()
        service = "event" if self.step == Steps.EVENT else "station"

        def done(services):
            if self.client_combo.currentText() == name and not (services or {}).get(service):
                self.client_warning.setText(f"⚠️ Client '{name}' does not appear to support the "
                                            f"{service.upper()} service. Please choose another client.")
                self.client_warning.show()
        run_task(check_client_services, name, on_success=done, capture_output=False)

    # ------------------------------------------------------------------
    # searching
    # ------------------------------------------------------------------
    def set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.sidebar.setEnabled(not busy)
        self.busyChanged.emit(busy)
        self._validate_dates()

    def search(self):
        if self._task is not None:
            return
        if not self._validate_dates():
            return
        self.apply_widgets_to_settings()
        self.persist()
        self.banner.hide()
        fetch = get_event_data if self.step == Steps.EVENT else get_station_data
        self._task = run_task(fetch, self.settings, on_success=self._on_search_result,
                              on_error=self._on_search_error, on_done=self._on_search_done)
        self.set_busy(True)

    def _on_search_done(self):
        self._task = None
        self.set_busy(False)

    def _on_search_error(self, msg):
        self.banner.error(friendly_error(msg))

    def _on_search_result(self, data):
        if self.step == Steps.EVENT:
            self.catalogs = data if data else Catalog()
            df = event_response_to_df(self.catalogs) if self.catalogs else pd.DataFrame()
        else:
            self.inventories = data if data else Inventory()
            df = station_response_to_df(self.inventories) if self.inventories else pd.DataFrame()
        self.set_dataframe(df)
        if df.empty:
            self.banner.warning("No data available for the selected settings.")
        else:
            self.banner.success(f"Found {len(df)} {self.noun}s.")
            self.map.fit_markers()

    def set_dataframe(self, df: pd.DataFrame):
        df = df.reset_index(drop=True)
        if not df.empty and SEL not in df.columns:
            df[SEL] = False
        self.df = df
        self.model.set_dataframe(df)
        self._apply_default_sort()
        self.table.resizeColumnsToContents()
        self._redraw_markers()
        self._update_count()

    def _on_filter_text(self, text):
        self.proxy.setFilterFixedString(text)
        self.proxy.invalidate()

    def _apply_default_sort(self):
        """Newest events first / stations by network; keep a user-chosen sort if there is one."""
        header = self.table.horizontalHeader()
        col, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        if self._user_sorted and 0 < col < self.model.columnCount():
            self.proxy.sort(col, order)
            return
        name, order = ("time", Qt.DescendingOrder) if self.step == Steps.EVENT else ("network", Qt.AscendingOrder)
        for c in range(self.model.columnCount()):
            if self.model._col_name(c) == name:
                self.table.sortByColumn(c, order)
                return

    def _redraw_markers(self):
        sel = set(self.df.index[self.df[SEL]]) if not self.df.empty else set()
        markers, legend = build_markers(self.df, self.step, sel)
        self.map.set_markers(markers, legend)

    def clear_all(self):
        self.df = pd.DataFrame()
        self.model.set_dataframe(self.df)
        self.map.set_markers([], "")
        if self.step == Steps.EVENT:
            self.catalogs = Catalog()
            self.settings.event.selected_catalogs = Catalog(events=None)
        else:
            self.inventories = Inventory()
            self.settings.station.selected_invs = None
        self.set_geo([])
        self.banner.hide()
        self._update_count()

    # ------------------------------------------------------------------
    # selection
    # ------------------------------------------------------------------
    def selected_labels(self) -> list:
        if self.df.empty or SEL not in self.df:
            return []
        return self.df.index[self.df[SEL]].tolist()

    def _update_count(self):
        if self.df.empty:
            self.count_label.setText(f"No {self.noun}s loaded")
            n_sel = 0
        else:
            n_sel = int(self.df[SEL].sum())
            self.count_label.setText(f"{len(self.df)} {self.noun}s · {n_sel} selected")
        self.selectionChanged.emit(n_sel)

    def _on_model_selection_changed(self, _labels):
        self.map.set_selected(self.selected_labels())
        self._update_count()

    def _check_rows(self, value: bool, visible_only: bool):
        if self.df.empty:
            return
        if visible_only:
            labels = [self.model.label_for_row(self.proxy.mapToSource(self.proxy.index(r, 0)).row())
                      for r in range(self.proxy.rowCount())]
        else:
            labels = list(self.df.index)
        self.model.set_checked(labels, value)

    def _check_highlighted(self, value: bool):
        rows = {self.proxy.mapToSource(ix).row() for ix in self.table.selectionModel().selectedRows()}
        self.model.set_checked([self.model.label_for_row(r) for r in rows], value)

    def _on_marker_clicked(self, layer, pos):
        if layer != "main" or self.df.empty or pos >= len(self.df):
            return
        label = self.df.index[pos]
        self.model.set_checked([label], not bool(self.df.at[label, SEL]))
        src = self.model.index(self.model.row_for_label(label), 0)
        proxy_ix = self.proxy.mapFromSource(src)
        if proxy_ix.isValid():
            self.table.scrollTo(proxy_ix)
            self.table.selectRow(proxy_ix.row())

    def _on_row_double_clicked(self, proxy_ix):
        row = self.proxy.mapToSource(proxy_ix).row()
        self.map.open_popup(row)

    def update_selected_data(self):
        """Write the table's checked rows into settings (selected_catalogs / selected_invs)."""
        labels = self.selected_labels()
        if self.step == Steps.EVENT:
            cat = Catalog(events=None)
            for i in labels:
                ev = self.catalogs[int(i)]
                if "place" in self.df.columns:
                    ev.extra = {"region": {"value": self.df.at[i, "place"], "namespace": "SEEDVAULT"}}
                cat.append(ev)
            self.settings.event.selected_catalogs = cat
        else:
            inv = None
            if labels:
                pairs = self.df.loc[labels, ["network", "station"]].drop_duplicates().itertuples(index=False)
                for net, sta in pairs:
                    part = self.inventories.select(network=net, station=sta)
                    inv = part if inv is None else inv + part
            self.settings.station.selected_invs = inv

    def n_selected(self) -> int:
        return len(self.selected_labels())

    # ------------------------------------------------------------------
    # areas
    # ------------------------------------------------------------------
    def _on_draw_created(self, constraints):
        if not constraints:
            return
        self.set_geo(self.geo() + constraints)
        if self.auto_search.isChecked():
            self.search()

    def _fill_area_tables(self):
        rects = [g.coords for g in self.geo() if isinstance(g.coords, RectangleArea)]
        circs = [g.coords for g in self.geo() if isinstance(g.coords, CircleArea)]
        for table, items, cols in ((self.rect_table, rects, ["min_lat", "max_lat", "min_lon", "max_lon"]),
                                   (self.circ_table, circs, ["lat", "lon", "min_radius", "max_radius"])):
            table.setRowCount(0)
            for c in items:
                self._add_area_row(table, [getattr(c, k) for k in cols])
        self.area_msg.clear()

    def _add_area_row(self, table, values):
        r = table.rowCount()
        table.insertRow(r)
        for j, v in enumerate(values):
            table.setItem(r, j, QTableWidgetItem(f"{float(v):.4f}".rstrip("0").rstrip(".")))

    def _delete_area_rows(self):
        for t in (self.rect_table, self.circ_table):
            for r in sorted({ix.row() for ix in t.selectedIndexes()}, reverse=True):
                t.removeRow(r)
        self._apply_area_tables()

    def _read_table(self, table):
        rows = []
        for r in range(table.rowCount()):
            vals = []
            for c in range(table.columnCount()):
                it = table.item(r, c)
                vals.append(float(it.text()) if it and it.text().strip() else 0.0)
            rows.append(vals)
        return rows

    def _apply_area_tables(self):
        try:
            rects, circs = self._read_table(self.rect_table), self._read_table(self.circ_table)
        except ValueError:
            self.area_msg.setText("All area values must be numbers.")
            return
        new = []
        for mn_lat, mx_lat, mn_lon, mx_lon in rects:
            if not is_valid_rectangle(mn_lat, mx_lat, mn_lon, mx_lon):
                self.area_msg.setText("Invalid rectangle: need min ≤ max, latitude in [-90, 90] and "
                                      "longitude in [0, 360].")
                return
            new.append(GeometryConstraint(coords=RectangleArea(min_lat=mn_lat, max_lat=mx_lat,
                                                               min_lon=mn_lon, max_lon=mx_lon)))
        for lat, lon, mn_r, mx_r in circs:
            if not is_valid_circle(lat, lon, mx_r, mn_r):
                self.area_msg.setText("Invalid circle: latitude in [-90, 90], longitude in [0, 360], "
                                      "max radius > 0 and 0 ≤ min radius ≤ max radius.")
                return
            new.append(GeometryConstraint(coords=CircleArea(lat=lat, lon=lon, min_radius=mn_r, max_radius=mx_r)))
        self.set_geo(new)

    # ------------------------------------------------------------------
    # previous step
    # ------------------------------------------------------------------
    def refresh_previous_step(self):
        """Show the previous step's selection on the map (stage 2)."""
        if self.prev_step == Steps.EVENT:
            sel = self.settings.event.selected_catalogs
            self.df_prev = event_response_to_df(sel) if sel else pd.DataFrame()
        elif self.prev_step == Steps.STATION:
            sel = self.settings.station.selected_invs
            self.df_prev = station_response_to_df(sel) if sel else pd.DataFrame()
        else:
            self.df_prev = pd.DataFrame()
        self.map.set_prev_markers(build_prev_markers(self.df_prev, self.prev_step) if self.prev_step else [])
        if self.prev_step is not None:
            n = len(self.df_prev)
            too_many = n > MAX_PREV_FOR_AREA
            self.around_btn.setEnabled(0 < n and not too_many)
            prev_noun = "event" if self.prev_step == Steps.EVENT else "station"
            self.around_msg.setText(
                f"No selected {prev_noun}s." if n == 0 else
                f"{n} selected {prev_noun}s – too many to search around individually (max "
                f"{MAX_PREV_FOR_AREA}); draw an area instead." if too_many else
                f"{n} selected {prev_noun}(s).")

    def _draw_area_around_prev(self):
        mn, mx = self.around_min.value(), self.around_max.value()
        if mn >= mx:
            self.around_msg.setText("Maximum radius must be greater than minimum radius.")
            return
        self.settings.event.min_radius, self.settings.event.max_radius = mn, mx
        keep = [g for g in self.geo() if g.geo_type != GeoConstraintType.CIRCLE]
        circles = [GeometryConstraint(geo_type=GeoConstraintType.CIRCLE,
                                      coords=CircleArea(lat=float(r.latitude), lon=float(r.longitude) % 360,
                                                        min_radius=mn, max_radius=mx))
                   for r in self.df_prev[["latitude", "longitude"]].itertuples(index=False)]
        self.set_geo(keep + circles)
        if self.auto_search.isChecked():
            self.search()

    def set_view_from(self, other: "SearchPanel"):
        lat, lng = other.map.center
        self.map.set_view(lat, lng, other.map.zoom)

    # ------------------------------------------------------------------
    # import / export
    # ------------------------------------------------------------------
    def _export_objects(self):
        selected = self.export_selected_only.isChecked()
        if selected:
            self.update_selected_data()
        if self.step == Steps.EVENT:
            return self.settings.event.selected_catalogs if selected else self.catalogs
        return self.settings.station.selected_invs if selected else self.inventories

    def _save_path(self, default_name, filt):
        path, _ = QFileDialog.getSaveFileName(self, "Export", default_name, filt)
        return path

    def export_csv(self):
        if self.df.empty:
            return self.banner.warning("Nothing to export yet.")
        df = self.df[self.df[SEL]] if self.export_selected_only.isChecked() else self.df
        path = self._save_path(f"{self.noun}_data.csv", "CSV (*.csv)")
        if path:
            df.drop(columns=[SEL], errors="ignore").to_csv(path, index=False)
            self.banner.success(f"Exported {len(df)} rows to {path}")

    def export_xml(self):
        obj = self._export_objects()
        if not obj:
            return self.banner.warning("Nothing to export yet.")
        if self.step == Steps.EVENT:
            path = self._save_path("events.qml", "QuakeML (*.qml *.xml)")
            fmt = "QUAKEML"
        else:
            path = self._save_path("stations.xml", "StationXML (*.xml)")
            fmt = "STATIONXML"
        if path:
            obj.write(path, format=fmt)
            self.banner.success(f"Exported to {path}")

    def export_txt(self):
        obj = self._export_objects()
        if not obj:
            return self.banner.warning("Nothing to export yet.")
        if self.step == Steps.EVENT:
            path, fmt = self._save_path("events.kml", "KML (*.kml)"), "KML"
        else:
            path, fmt = self._save_path("stations.txt", "Text (*.txt)"), "STATIONTXT"
        if path:
            obj.write(path, format=fmt)
            self.banner.success(f"Exported to {path}")

    def export_bibtex(self):
        inv = self._export_objects()
        if not inv:
            return self.banner.warning("Nothing to export yet.")
        path = self._save_path("stations.bib", "BibTeX (*.bib)")
        if not path:
            return
        self.banner.info("Fetching BibTeX citations…")
        run_task(inventory_to_bibtex, inv, path,
                 on_success=lambda _: self.banner.success(f"Exported BibTeX to {path}"),
                 on_error=lambda m: self.banner.error(f"BibTeX export failed: {m}"))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "",
                                              "Supported (*.xml *.qml *.quakeml *.cfg);;All files (*)")
        if not path:
            return
        try:
            if path.lower().endswith(".cfg"):
                self._import_cfg(path)
            elif self.step == Steps.EVENT:
                self.catalogs = read_events(path)
                self.set_dataframe(event_response_to_df(self.catalogs))
                self.banner.success(f"Imported {len(self.catalogs)} events from {os.path.basename(path)}")
            else:
                self.inventories = read_inventory(path)
                self.set_dataframe(station_response_to_df(self.inventories))
                self.banner.success(f"Imported {len(self.df)} stations from {os.path.basename(path)}")
            self.map.fit_markers()
        except Exception as e:  # noqa: BLE001
            self.banner.error(f"Import failed: {e}")

    def _import_cfg(self, path):
        new = SeismoLoaderSettings.from_cfg_file(path)
        if new.status_handler.has_errors():
            self.banner.error("Please resolve the errors in the imported file:<br><pre>"
                              f"{new.status_handler.generate_status_report('errors')}</pre>")
            return
        new.client_url_mapping.load()
        new.event.geo_constraint, new.station.geo_constraint = [], []
        new.event.selected_catalogs, new.station.selected_invs = Catalog(events=None), None
        self.clear_all()
        for k, v in vars(new).items():
            setattr(self.settings, k, v)
        self.load_from_settings()
        msg = "Settings imported successfully."
        if new.status_handler.has_warnings():
            msg += f"<br><pre>{new.status_handler.generate_status_report('warnings')}</pre>"
        self.banner.success(msg)
