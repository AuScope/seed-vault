"""Regression checks for reported GUI issues (run via tests/test_qt_gui.py)."""
import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS","--no-sandbox --disable-gpu")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer, Qt, QPointF, QPoint
from PySide6.QtGui import QWheelEvent
import obspy
from obspy import read_events, Stream
app = QApplication(sys.argv)
def wait(ms, until=None, timeout=10):
    import time as _t; t0 = _t.time()
    while True:
        l=QEventLoop(); QTimer.singleShot(ms,l.quit); l.exec()
        if until is None or until() or _t.time()-t0 > timeout: return
FAILS = []
def check(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: FAILS.append(m)

# 2) composite clients hidden
from seed_vault.service.settings_store import default_settings
clients = list(default_settings().client_url_mapping.get_clients())
check("EARTHSCOPE+USGS" not in clients and "EARTHSCOPE" in clients and "USGS" in clients, "composite client hidden, real ones kept")

# 1) settings page: no 'editing failed'
msgs = []
from PySide6.QtCore import qInstallMessageHandler
qInstallMessageHandler(lambda m, c, s: msgs.append(s))
from seed_vault.qt.settings_page import SettingsPage
sp = SettingsPage(); sp.show(); wait(200)
check(not any("editing failed" in m for m in msgs), f"no 'editing failed' warnings ({len(msgs)} msgs)")
qInstallMessageHandler(None)

# 7) checking a row keeps the order
from seed_vault.qt.search_panel import SearchPanel
from seed_vault.enums.ui import Steps
from seed_vault.service.events import event_response_to_df
s = default_settings(); s.client_url_mapping.load()
p = SearchPanel(s, Steps.EVENT); p.resize(1300, 800); p.show(); wait(300)
p.set_dataframe(event_response_to_df(read_events()))
order = lambda: [p.proxy.index(r, 3).data() for r in range(p.proxy.rowCount())]
before = order()
times = [p.model.dataframe().iloc[p.proxy.mapToSource(p.proxy.index(r,0)).row()]["time"] for r in range(3)]
check(times == sorted(times, reverse=True), "default sort: newest first")
p.table.sortByColumn(0, Qt.AscendingOrder)   # even when sorted by the check column
before = order()
p.proxy.setData(p.proxy.index(2, 0), Qt.Checked, Qt.CheckStateRole); wait(50)
check(order() == before and p.n_selected() == 1, "checking a row doesn't move it")
p._on_filter_text("turkey"); wait(50); check(p.proxy.rowCount() == 2, "filter still works")
p._on_filter_text("")
wait(2500); pass

# 5) + 6) waveform page
from seed_vault.qt.waveform_page import WaveformPage
s.event.selected_catalogs = read_events()
st = Stream()
for ev in s.event.selected_catalogs:
    for sta in ("AAA", "BBB"):
        for tr in obspy.read():
            o = ev.origins[0]; tr.stats.station = sta; tr.stats.network = "XX"; tr.stats.starttime = o.time + 60
            tr.stats.resource_id = str(ev.resource_id); tr.stats.p_arrival = str(o.time + 80); tr.stats.distance_km = 100
            st += tr
w = WaveformPage(s); w.resize(1200, 700); w.show()
w.stream = st; w._populate_selectors(); w.request_replot(); wait(2000)
w.sta_combo.setCurrentText("AAA"); wait(1500)       # stale station filter from event view
w.view_station.setChecked(True); wait(2000)
labels = lambda: sorted({t.get_text()[:6] for ax in w.current_figure.axes for t in ax.texts}) if w.current_figure else []
check(not w.sta_combo.isVisibleTo(w) and w.cha_combo.isVisibleTo(w), "station view hides net/sta filters")
a = labels(); w.item_combo.setCurrentIndex(1); wait(2000); b = labels()
check(a == ["XX.AAA"] and b == ["XX.BBB"], f"switching station updates plot ({a} -> {b})")
canvas = w.plot_scroll.widget(); sb = w.plot_scroll.verticalScrollBar()
check(sb.maximum() > 0, f"plot taller than view (max scroll {sb.maximum()})")
def wheel(mods):
    ev = QWheelEvent(QPointF(300, 100), QPointF(canvas.mapToGlobal(QPoint(300, 100))), QPoint(0, 0), QPoint(0, -240),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(canvas, ev); wait(100)
v0 = sb.value(); wheel(Qt.NoModifier); check(sb.value() > v0, f"wheel scrolls the page ({v0} -> {sb.value()})")
x0 = w.current_figure.axes[0].get_xlim(); wheel(Qt.ControlModifier); x1 = w.current_figure.axes[0].get_xlim()
check((x1[1]-x1[0]) > (x0[1]-x0[0]), f"ctrl+wheel zooms time axis {x0} -> {x1}")

# custom per-service client URLs in Settings -------------------------------------
import io as _io, threading as _th
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
_cat = _io.BytesIO(); read_events().write(_cat, format="QUAKEML")
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/custom/quakes/1/query":
            b = _cat.getvalue(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass
_srv = ThreadingHTTPServer(("127.0.0.1", 0), _H); _th.Thread(target=_srv.serve_forever, daemon=True).start()
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
_base = f"http://127.0.0.1:{_srv.server_address[1]}"
sp2 = SettingsPage(); sp2.show(); wait(100)
check(sp2.client_table.columnCount() == 5, "client table has base + 3 service columns")
def _set_row(vals):
    sp2.client_table.setRowCount(0); sp2._add_row(sp2.client_table, vals)
_set_row(["GEOFON", "https://x.org", "", "", ""]);   check(sp2.save() is False and "built-in" in sp2.banner.label.text(), "rejects built-in name")
_set_row(["BAD NAME", "https://x.org", "", "", ""]); check(sp2.save() is False, "rejects invalid name")
_set_row(["ONLYNONE", "", "", "none", ""]);          check(sp2.save() is False and "base URL or at least one" in sp2.banner.label.text(), "needs base or service URL")
_set_row(["BADURL", "", "", "ftp://x", ""]);         check(sp2.save() is False and "http" in sp2.banner.label.text(), "rejects non-http service URL")
_set_row(["MYQUAKES", "", "none", f"{_base}/custom/quakes/1", "none"])
check(sp2.save() is True, "saves custom client with only an event URL")
sp2.reload(); wait(100)
rows = sp2._client_rows()
check(any(r["client"] == "MYQUAKES" and r["event"] == f"{_base}/custom/quakes/1" and r["station"] == "none" for r in rows),
      "custom service URLs survive save/reload")
r = [i for i, x in enumerate(rows) if x["client"] == "MYQUAKES"][0]
sp2.client_table.selectRow(r); sp2.test_client()
wait(200, until=lambda: sp2.test_btn.isEnabled(), timeout=30)
txt = sp2.test_result.text()
check("✅ <b>event</b>" in txt and "❌ <b>station</b>: not offered" in txt and "❌ <b>dataselect</b>: not offered" in txt, "Test button reports per-service status")
from seed_vault.service.seismoloader import get_events
s2 = default_settings(); s2.event.client = "MYQUAKES"; s2.waveform.client = "MYQUAKES"; s2.event.geo_constraint = []
s2.event.min_magnitude, s2.event.max_magnitude = -2, 10
s2.event.date_config.start_time, s2.event.date_config.end_time = "2012-01-01T00:00:00", "2013-01-01T00:00:00"
evs = get_events(s2)
check(sum(len(c) for c in evs) == 3 if isinstance(evs, list) else len(evs) == 3, "backend get_events uses the custom event URL")
sp2.client_table.setRowCount(0); sp2.save()   # clean up

print("FAILURES:", FAILS)
sys.exit(1 if FAILS else 0)
