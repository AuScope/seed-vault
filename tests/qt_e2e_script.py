"""Drive the Qt app headlessly through the main workflows using ObsPy sample data.

Run directly (``python tests/qt_e2e_script.py [screenshot_dir]``) or via tests/test_qt_gui.py.
Network calls are replaced with ObsPy example data, so no FDSN access is needed.
"""
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
import obspy
from obspy import read_events, read_inventory, Stream, UTCDateTime

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_screenshots")
os.makedirs(OUT, exist_ok=True)

import seed_vault.qt.search_panel as sp
import seed_vault.qt.waveform_page as wp
import seed_vault.qt.continuous_page as cp
import seed_vault.qt.run_config_page as rcp
from seed_vault.qt.app import MainWindow
from seed_vault.qt.workers import install_stream_router

CAT = read_events(); INV = read_inventory()
def fake_events(settings):
    print("Running get_events (fake)…"); time.sleep(0.3); return CAT.copy()
def fake_stations(settings):
    print("Running get_stations (fake)…"); time.sleep(0.3); return INV.copy()
def fake_run_event(settings, stop_event=None):
    print("run_event (fake): requesting data\r50%\r100%\ndone")
    st = Stream()
    for ev in settings.event.selected_catalogs:
        base = obspy.read()
        o = ev.origins[0]
        for i, tr in enumerate(base):
            tr.stats.starttime = o.time + 60
            tr.stats.resource_id = str(ev.resource_id)
            tr.stats.p_arrival = str(o.time + 80)
            tr.stats.distance_km = 1234.5 + i
            tr.stats.event_time = o.time
            tr.stats.event_magnitude = ev.magnitudes[0].mag
            tr.stats.event_region = "Test region"
            st += tr
    missing = {str(settings.event.selected_catalogs[0].resource_id): {"GR.FUR": "ALL", "BW.RJOB": ["BW.RJOB..EHZ"]}}
    return st, missing
def fake_run_continuous(settings, stop_event=None):
    for i in range(5):
        if stop_event is not None and stop_event.is_set(): return False
        print(f"continuous chunk {i}"); time.sleep(0.1)
    return True
sp.get_event_data = fake_events; sp.get_station_data = fake_stations
wp.run_event = fake_run_event; cp.run_continuous = fake_run_continuous
sp.check_client_services = lambda *a, **k: {"event": True, "station": True, "dataselect": True}
wp.check_client_services = sp.check_client_services

QCoreApplication.setOrganizationName("AuScope-test"); QCoreApplication.setApplicationName("SEED Vault test")
install_stream_router()
app = QApplication(sys.argv)

def wait(ms=300, until=None, timeout=10):
    t0 = time.time()
    while True:
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()
        if until is None or until() or time.time() - t0 > timeout: return
def shot(w, name):
    wait(1200)
    w.grab().save(os.path.join(OUT, name + ".png")); print("shot", name)
def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: FAILS.append(msg)
FAILS = []

win = MainWindow(); win.resize(1500, 950); win.show(); wait(500)
wf = win.page(0)
shot(win, "00_start")
# --- event based flow
idx = [i for i in range(wf.flow_combo.count()) if wf.flow_combo.itemData(i).name == "EVENT_BASED"][0]
wf.flow_combo.setCurrentIndex(idx); wf.start(); wait(1500)
ep = wf.event_panel
wait(200, until=lambda: ep.map.is_ready(), timeout=15)
check(ep.map.is_ready(), "event map ready")
wf.next_stage(); wait(200)
check(wf.stage == 1 and wf.flow_banner.isVisible(), "Next blocked with no selection")
ep.search(); wait(200, until=lambda: ep._task is None and not ep.df.empty)
check(len(ep.df) == 3, f"events loaded ({len(ep.df)})")
ep._check_rows(True, visible_only=True); wait(200)
check(ep.n_selected() == 3, "select all events")
ep._on_marker_clicked("main", 1); wait(100)
check(ep.n_selected() == 2, "marker click toggles selection")
ep.proxy.setFilterFixedString("turkey"); wait(100)
check(ep.proxy.rowCount() == 2, f"table filter works ({ep.proxy.rowCount()} rows)")
ep.proxy.setFilterFixedString("")
shot(win, "01_events")
wf.next_stage(); wait(800)
check(wf.stage == 2, "advanced to stations")
stp = wf.station_panel
check(len(stp.df_prev) == 2, f"previous selection shown ({len(stp.df_prev)})")
stp.around_min.setValue(0); stp.around_max.setValue(30); stp.auto_search.setChecked(False)
stp._draw_area_around_prev(); wait(200)
check(len(stp.geo()) == 2 and stp.circ_table.rowCount() == 2, "search-around draws circles")
stp.search(); wait(200, until=lambda: stp._task is None and not stp.df.empty)
check(len(stp.df) > 0, f"stations loaded ({len(stp.df)})")
stp._check_rows(True, visible_only=True)
shot(win, "02_stations")
wf.next_stage(); wait(800)
check(wf.stage == 3, "advanced to waveforms")
wv = wf.waveform_page
wv.start_download(); wait(200, until=lambda: wv._download is None and wv.current_figure is not None, timeout=20)
wait(800)
check(len(wv.stream) == 6, f"waveforms downloaded ({len(wv.stream)})")
check("done" in wv.log.toPlainText() and "Running run_event" in wv.log.toPlainText(), "log captured stdout")
check("100%" in wv.log.toPlainText() and "50%" not in wv.log.toPlainText(), "carriage-return progress collapsed")
check(wv.current_figure is not None, "figure rendered")
check(wv.missing_model.rowCount() == 1, "missing data table filled")
shot(win, "03_waveforms")
wv.view_station.setChecked(True); wait(1500)
check(wv.item_combo.count() >= 1 and wv.current_figure is not None, "station view")
shot(win, "04_waveforms_station_view")
wv.tabs.setCurrentIndex(1); shot(win, "05_log")
wf.previous_stage(); wait(200)
check(wf.stage == 2 and not wv.stream, "previous clears waveform results")

# --- continuous flow
wf.previous_stage(); wf.previous_stage(); wait(200)
idx = [i for i in range(wf.flow_combo.count()) if wf.flow_combo.itemData(i).name == "CONTINUOUS"][0]
wf.flow_combo.setCurrentIndex(idx); wf.start(); wait(1000)
p = wf.station_panel; p.search(); wait(200, until=lambda: p._task is None and not p.df.empty)
p._check_rows(True, visible_only=True); wf.next_stage(); wait(300)
c = wf.continuous_page
check("GR" in c.nslc_label.text(), "NSLC summary filled")
c.start(); wait(200, until=lambda: c._task is None, timeout=10)
check("continuous chunk 4" in c.log.toPlainText(), "continuous log captured")
shot(win, "06_continuous")

# --- other pages
win.nav.setCurrentIndex(1); wait(500); shot(win, "07_run_config")
win.nav.setCurrentIndex(2); wait(500)
db = win.page(2); db.execute(); wait(200, until=lambda: db._task is None)
check(db.banner.isVisible(), "db query ran")
shot(win, "08_db")
win.nav.setCurrentIndex(3); wait(300); shot(win, "09_settings")
print("FAILURES:", FAILS)
win.close(); win.deleteLater(); wait(200)
sys.exit(1 if FAILS else 0)
