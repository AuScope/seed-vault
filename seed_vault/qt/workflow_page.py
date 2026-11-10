"""Main flows: event-based, station-based and continuous.

Qt port of ``seed_vault.ui.components.workflows_combined.CombinedBasedWorkflow``.
"""
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QStackedWidget, QVBoxLayout, QWidget

from seed_vault.enums.config import WorkflowType
from seed_vault.enums.ui import Steps
from seed_vault.qt.continuous_page import ContinuousPage
from seed_vault.qt.search_panel import SearchPanel
from seed_vault.qt.waveform_page import WaveformPage
from seed_vault.qt.widgets import Banner, button, hbox
from seed_vault.service.settings_store import default_settings, load_settings, save_settings
from seed_vault.utils.constants import DOC_BASE_URL

DOC_LINKS = {
    "Workflow overview": f"{DOC_BASE_URL}/app_main_flows.html",
    "Event-based workflow": f"{DOC_BASE_URL}/flows/events_based.html",
    "Station-based workflow": f"{DOC_BASE_URL}/flows/station_based.html",
    "Download continuous data": f"{DOC_BASE_URL}/flows/continuous_based.html",
}


class WorkflowPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = None
        self.event_panel: Optional[SearchPanel] = None
        self.station_panel: Optional[SearchPanel] = None
        self.waveform_page: Optional[WaveformPage] = None
        self.continuous_page: Optional[ContinuousPage] = None
        self.stages: List[QWidget] = []
        self.stage = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.outer = QStackedWidget()
        lay.addWidget(self.outer)
        self.outer.addWidget(self._build_start_page())

        flow = QWidget()
        fl = QVBoxLayout(flow)
        fl.setContentsMargins(6, 6, 6, 0)
        self.prev_btn = button("◀  Previous", self.previous_stage)
        self.next_btn = button("Next  ▶", self.next_stage, primary=True)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.step_label = QLabel()
        self.step_label.setStyleSheet("color: #666;")
        fl.addLayout(hbox(self.prev_btn, None, self.title, None, self.step_label, self.next_btn))
        self.flow_banner = Banner()
        fl.addWidget(self.flow_banner)
        self.stack = QStackedWidget()
        fl.addWidget(self.stack, 1)
        self.outer.addWidget(flow)

    # ------------------------------------------------------------------
    # stage 0
    # ------------------------------------------------------------------
    def _build_start_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.addWidget(QLabel("<h1>🌎 SEED Vault</h1>"
                             "<p>Search, view and download seismic data from FDSN servers.</p>"))
        self.flow_combo = QComboBox()
        for wf in WorkflowType:
            self.flow_combo.addItem(wf.value, wf)
        self.flow_combo.currentIndexChanged.connect(self._update_description)
        self.start_btn = button("Start", self.start, primary=True)
        self.start_btn.setMinimumWidth(120)
        lay.addWidget(QLabel("<b>Select the seismic data request flow</b>"))
        lay.addLayout(hbox(self.flow_combo, self.start_btn, None))
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setStyleSheet("background: #e8f1fb; color: #1c4f80; padding: 10px; border-radius: 4px;")
        lay.addWidget(self.description)
        links = "".join(f'<li><a href="{u}">{n}</a></li>' for n, u in DOC_LINKS.items())
        docs = QLabel(f"For further information please see the documentation:<ul>{links}</ul>")
        docs.setOpenExternalLinks(True)
        lay.addWidget(docs)
        self.start_banner = Banner()
        lay.addWidget(self.start_banner)
        self.reset_btn = button("🔄 Reset settings to default", self.reset_settings)
        self.reset_btn.hide()
        lay.addLayout(hbox(self.reset_btn, None))
        lay.addStretch(1)
        self._load_settings_for_start()
        return w

    def _load_settings_for_start(self) -> bool:
        try:
            self.settings = load_settings()
        except Exception as e:  # noqa: BLE001
            self.start_banner.error(f"⚠️ Could not read the configuration: {e}")
            self.reset_btn.show()
            return False
        if self.settings.status_handler.has_errors():
            report = self.settings.status_handler.generate_status_report("errors")
            self.start_banner.error("⚠️ Initialization failed due to invalid parameters.<br><pre>"
                                    f"{report}</pre>Try resetting the settings.")
            self.reset_btn.show()
            return False
        self.start_banner.hide()
        self.reset_btn.hide()
        self._select_flow(self.settings.selected_workflow)
        return True

    def _select_flow(self, wf):
        for i in range(self.flow_combo.count()):
            if self.flow_combo.itemData(i) == wf:
                self.flow_combo.setCurrentIndex(i)
        self._update_description()

    def _update_description(self, *_):
        wf = self.flow_combo.currentData()
        if wf is not None:
            self.description.setText(wf.description)

    def reset_settings(self):
        save_settings(default_settings())
        self._load_settings_for_start()
        self.start_banner.success("Settings have been reset to default.")

    # ------------------------------------------------------------------
    # build a flow
    # ------------------------------------------------------------------
    def _clear_stages(self):
        for w in self.stages:
            self.stack.removeWidget(w)
            w.deleteLater()
        self.stages = []
        self.event_panel = self.station_panel = self.waveform_page = self.continuous_page = None

    def start(self):
        chosen = self.flow_combo.currentData()
        if not self._load_settings_for_start():
            return
        self._select_flow(chosen)
        self._clear_stages()
        s = self.settings
        s.selected_workflow = chosen
        s.set_download_type_from_workflow()
        wf = s.selected_workflow
        if wf == WorkflowType.EVENT_BASED:
            self.event_panel = SearchPanel(s, Steps.EVENT, None, 1)
            self.station_panel = SearchPanel(s, Steps.STATION, Steps.EVENT, 2)
            self.waveform_page = WaveformPage(s)
            self.stages = [self.event_panel, self.station_panel, self.waveform_page]
        elif wf == WorkflowType.STATION_BASED:
            self.station_panel = SearchPanel(s, Steps.STATION, None, 1)
            self.event_panel = SearchPanel(s, Steps.EVENT, Steps.STATION, 2)
            self.waveform_page = WaveformPage(s)
            self.stages = [self.station_panel, self.event_panel, self.waveform_page]
        else:
            self.station_panel = SearchPanel(s, Steps.STATION, None, 1)
            self.continuous_page = ContinuousPage(s)
            self.stages = [self.station_panel, self.continuous_page]
        for w in self.stages:
            self.stack.addWidget(w)
            if isinstance(w, SearchPanel):
                w.busyChanged.connect(lambda busy: self.next_btn.setEnabled(not busy))
                w.selectionChanged.connect(lambda n: n and self.flow_banner.hide())
        self.outer.setCurrentIndex(1)
        self._show_stage(1)

    def _titles(self):
        wf = self.settings.selected_workflow
        if wf == WorkflowType.EVENT_BASED:
            return ["Step 1: Search & select events", "Step 2: Search & select stations", "Step 3: Waveforms"]
        if wf == WorkflowType.STATION_BASED:
            return ["Step 1: Search & select stations", "Step 2: Search & select events", "Step 3: Waveforms"]
        return ["Step 1: Search & select stations", "Step 2: Get continuous waveforms"]

    def _show_stage(self, n: int):
        self.stage = n
        titles = self._titles()
        self.title.setText(titles[n - 1])
        self.step_label.setText(f"{n} / {len(titles)}")
        self.next_btn.setVisible(n < len(self.stages))
        self.next_btn.setEnabled(True)
        self.flow_banner.hide()
        self.stack.setCurrentWidget(self.stages[n - 1])

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------
    def previous_stage(self):
        if self.stage <= 1:
            # back to the flow chooser; keep nothing (fresh start next time)
            for p in (self.event_panel, self.station_panel):
                if p is not None:
                    p.persist()
            self.outer.setCurrentIndex(0)
            self._load_settings_for_start()
            return
        current = self.stages[self.stage - 1]
        if isinstance(current, WaveformPage):
            current.reset()
        elif isinstance(current, ContinuousPage):
            current.reset()
        self._show_stage(self.stage - 1)

    def _error(self, msg):
        self.flow_banner.error(msg)
        return False

    def _validate_and_hand_off(self) -> bool:
        s, wf = self.settings, self.settings.selected_workflow
        if self.stage == 1:
            if wf == WorkflowType.EVENT_BASED:
                self.event_panel.update_selected_data()
                if not s.event.selected_catalogs:
                    return self._error("Please select at least one event to proceed to the next step.")
                self.event_panel.persist()
                s.station.date_config.start_time = s.event.date_config.start_time
                s.station.date_config.end_time = s.event.date_config.end_time
                self._enter_second_search(self.station_panel, self.event_panel)
            elif wf == WorkflowType.STATION_BASED:
                self.station_panel.update_selected_data()
                if not s.station.selected_invs:
                    return self._error("Please select at least one station to proceed to the next step.")
                self.station_panel.persist()
                s.event.date_config.start_time = s.station.date_config.start_time
                s.event.date_config.end_time = s.station.date_config.end_time
                s.waveform.client = s.station.client
                self._enter_second_search(self.event_panel, self.station_panel)
            else:
                self.station_panel.update_selected_data()
                if not s.station.selected_invs:
                    return self._error("Please select at least one station to proceed to the next step.")
                self.station_panel.persist()
                self.continuous_page.load_from_settings()
        elif self.stage == 2:
            if wf == WorkflowType.EVENT_BASED:
                self.station_panel.update_selected_data()
                if not s.station.selected_invs:
                    return self._error("Please select at least one station to proceed to the next step.")
                self.station_panel.persist()
                s.waveform.client = s.station.client
            elif wf == WorkflowType.STATION_BASED:
                self.event_panel.update_selected_data()
                if not s.event.selected_catalogs:
                    return self._error("Please select at least one event to proceed to the next step.")
                self.event_panel.persist()
            self.waveform_page.load_from_settings()
            self.waveform_page.reset()
        return True

    @staticmethod
    def _enter_second_search(panel: SearchPanel, first: SearchPanel):
        panel.load_from_settings()
        panel.sync_dates_from_previous_step()
        panel.refresh_previous_step()
        panel.set_view_from(first)

    def next_stage(self):
        if self.stage < len(self.stages) and self._validate_and_hand_off():
            self._show_stage(self.stage + 1)

    def shutdown(self):
        for w in self.stages:
            for name in ("cancel_download", "cancel"):
                fn = getattr(w, name, None)
                if callable(fn):
                    fn()
