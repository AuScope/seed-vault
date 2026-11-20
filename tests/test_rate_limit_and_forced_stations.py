"""HTTP 429 handling (honour Retry-After, minimum wait, shared per host, cancellable),
error classification, and force_stations obeying the location/channel filters."""
import copy
import io
import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from obspy import UTCDateTime, read_events, read_inventory
from obspy.clients.fdsn.header import (FDSNNoDataException, FDSNTooManyRequestsException,
                                       FDSNServiceUnavailableException)

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery
from seed_vault.service import fdsn_client as fc
from seed_vault.service import seismoloader as sl


# ---------------------------------------------------------------- fake server
class _Server:
    """Answers /fdsnws/event/1/query with a scripted list of (status, retry_after) then 200s."""

    def __init__(self):
        cat = io.BytesIO()
        read_events().write(cat, format="QUAKEML")
        self.body = cat.getvalue()
        self.script, self.hits = [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(time.monotonic())
                if outer.script:
                    code, retry_after = outer.script.pop(0)
                    self.send_response(code)
                    if retry_after is not None:
                        self.send_header("Retry-After", str(retry_after))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    fc._host_not_before.clear()
    srv = _Server()
    yield srv
    srv.httpd.shutdown()
    fc._host_not_before.clear()


def _client(url):
    return fc.SeedVaultClient(url, _discover_services=False, timeout=10)


def _get(client):
    return client.get_events(starttime=UTCDateTime(2012, 1, 1), endtime=UTCDateTime(2013, 1, 1))


# ---------------------------------------------------------------- Retry-After
def test_parse_retry_after():
    now = time.time()
    assert fc.parse_retry_after("120") == 120
    assert fc.parse_retry_after(" 0 ") == 0
    assert fc.parse_retry_after(formatdate(now + 90, usegmt=True), now=now) == pytest.approx(90, abs=1)
    assert fc.parse_retry_after(formatdate(now - 90, usegmt=True), now=now) == 0
    assert fc.parse_retry_after("soon") is None and fc.parse_retry_after(None) is None


def test_429_waits_retry_after_then_succeeds(server, monkeypatch):
    monkeypatch.setattr(fc, "MIN_429_WAIT", 0.5)
    server.script = [(429, 2)]                  # server asks for 2 s, more than the minimum
    t0 = time.monotonic()
    cat = _get(_client(server.url))
    assert len(cat) == 3 and len(server.hits) == 2
    assert server.hits[1] - server.hits[0] >= 1.9          # honoured Retry-After, didn't retry at once
    assert time.monotonic() - t0 < 10


def test_429_without_header_waits_minimum(server, monkeypatch):
    monkeypatch.setattr(fc, "MIN_429_WAIT", 1.0)
    server.script = [(429, None)]
    _get(_client(server.url))
    assert server.hits[1] - server.hits[0] >= 0.95


def test_short_retry_after_is_raised_to_minimum(server, monkeypatch):
    monkeypatch.setattr(fc, "MIN_429_WAIT", 1.5)
    server.script = [(429, 0)]                  # "retry immediately" is not allowed
    _get(_client(server.url))
    assert server.hits[1] - server.hits[0] >= 1.45


def test_default_minimum_is_at_least_a_minute():
    assert fc.MIN_429_WAIT >= 60


def test_wait_is_shared_by_other_clients_of_same_host(server, monkeypatch):
    monkeypatch.setattr(fc, "MIN_429_WAIT", 1.5)
    server.script = [(429, None)]
    a, b = _client(server.url), _client(server.url)
    t = threading.Thread(target=_get, args=(a,))
    t.start()
    time.sleep(0.3)                              # a has hit the 429 and is waiting
    _get(b)                                      # b must not slip in during a's wait
    t.join()
    assert len(server.hits) == 3
    assert min(server.hits[1:]) - server.hits[0] >= 1.4


def test_gives_up_when_server_asks_for_too_long(server, monkeypatch):
    monkeypatch.setattr(fc, "MAX_429_WAIT", 5)
    server.script = [(429, 3600)]
    with pytest.raises(FDSNTooManyRequestsException):
        _get(_client(server.url))
    assert len(server.hits) == 1


def test_wait_can_be_cancelled(server, monkeypatch):
    monkeypatch.setattr(fc, "MIN_429_WAIT", 30)
    server.script = [(429, None)]
    c = _client(server.url)
    c.stop_event = threading.Event()
    threading.Timer(0.5, c.stop_event.set).start()
    t0 = time.monotonic()
    with pytest.raises(Exception) as ei:
        _get(c)
    assert time.monotonic() - t0 < 5
    assert fc.classify_error(ei.value) in ("Cancelled", "Connection error") or "Cancelled" in str(ei.value)


def test_make_client_returns_rate_limited_client(server):
    c = fc.build_client(server.url, _discover_services=False)
    assert isinstance(c, fc.SeedVaultClient) and isinstance(c._url_opener, fc.RateLimitedOpener)
    c.set_credentials("u", "p")                  # re-creating the opener keeps the wrapper
    assert isinstance(c._url_opener, fc.RateLimitedOpener)


# ---------------------------------------------------------------- error types
@pytest.mark.parametrize("exc, label", [
    (FDSNNoDataException("No data available for request."), "204 No data"),
    (FDSNTooManyRequestsException("Too many"), "429 Too many requests"),
    (FDSNServiceUnavailableException("down"), "503 Service unavailable"),
    (HTTPError("u", 403, "Forbidden", {}, None), "403 Forbidden"),
    (URLError("timed out"), "Timeout"),
    (URLError("connection refused"), "Connection error"),
    (fc.DownloadCancelled("x"), "Cancelled"),
    (ValueError("weird"), "ValueError"),
])
def test_classify_error(exc, label):
    assert fc.classify_error(exc) == label


def test_archive_request_tallies_error_types(tmp_path):
    s = SeismoLoaderSettings.create_default()
    s.sds_path, s.db_path = str(tmp_path / "sds"), str(tmp_path / "db.sqlite")
    db = sl.setup_paths(s)[1]
    client = MagicMock()
    client.services = {"dataselect": {}}
    client.get_waveforms.side_effect = [FDSNTooManyRequestsException("x"), FDSNNoDataException("y")]
    tally = fc.ErrorTally()
    for sta in ("AAA", "BBB"):
        sl.archive_request(("XX", sta, "", "BHZ", "2020-01-01T00:00:00", "2020-01-01T01:00:00"),
                           {"open": client}, s.sds_path, db, tally)
    assert tally.counts == {"429 Too many requests": 1, "204 No data": 1}
    assert tally.summary().startswith("Download errors by type:")


# ---------------------------------------------------------------- force_stations
def _inv_with_channels():
    """GR.FUR with 00.HHZ, 00.LHZ, 10.HHZ."""
    inv = read_inventory().select(network="GR", station="FUR")
    sta = inv[0][0]
    base = sta.channels[0]
    sta.channels = []
    for loc, code in (("00", "HHZ"), ("00", "LHZ"), ("10", "HHZ")):
        c = copy.deepcopy(base)
        c.location_code, c.code = loc, code
        sta.channels.append(c)
    return inv


def _settings_for_force(loc, cha):
    s = SeismoLoaderSettings.create_default()
    s.station.local_inventory = None
    s.station.geo_constraint = []
    s.station.network, s.station.station = "IU", "ANMO"
    s.station.location, s.station.channel = loc, cha
    s.station.highest_samplerate_only = False
    s.waveform.channel_pref = s.waveform.location_pref = ""
    s.station.date_config.start_time = UTCDateTime("2020-01-01").datetime
    s.station.date_config.end_time = UTCDateTime("2021-01-01").datetime
    s.station.force_stations = [SeismoQuery(cmb_str_n_s="GR.FUR",
                                            starttime=UTCDateTime("1990-01-01").datetime,
                                            endtime=UTCDateTime("1991-01-01").datetime)]
    s.station.exclude_stations = []
    return s


def _station_client(main_result):
    c = MagicMock()
    c.services = {"station": {k: True for k in ("network", "station", "location", "channel", "starttime",
                                                "endtime", "includerestricted", "level")}}
    c.base_url = "http://x"
    calls = []

    def get_stations(**kw):
        calls.append(kw)
        if kw["network"] == "GR":
            return _inv_with_channels()
        if isinstance(main_result, Exception):
            raise main_result
        return main_result
    c.get_stations.side_effect = get_stations
    return c, calls


def _codes(inv):
    return sorted(f"{n.code}.{s.code}.{c.location_code}.{c.code}" for n in inv for s in n for c in s)


def test_forced_station_obeys_location_and_channel_filters():
    s = _settings_for_force("00", "HH?")
    client, calls = _station_client(FDSNNoDataException("none"))   # main search finds nothing
    with patch.object(sl, "make_client", return_value=client):
        inv = sl.get_stations(s)
    assert _codes(inv) == ["GR.FUR.00.HHZ"]                 # LHZ and location 10 filtered out
    forced = [c for c in calls if c["network"] == "GR"][0]
    assert forced["location"] == "00" and forced["channel"] == "HH?"
    assert forced["starttime"] == UTCDateTime("2020-01-01")  # current range, not the stale one
    assert "includerestricted" in forced and "level" in forced


def test_forced_station_with_comma_and_blank_location_filters():
    s = _settings_for_force("10,--", "?HZ")
    client, _ = _station_client(FDSNNoDataException("none"))
    with patch.object(sl, "make_client", return_value=client):
        inv = sl.get_stations(s)
    assert _codes(inv) == ["GR.FUR.10.HHZ"]


def test_forced_station_not_duplicated_when_also_found():
    s = _settings_for_force("*", "*")
    client, _ = _station_client(_inv_with_channels())       # main search also returns GR.FUR
    with patch.object(sl, "make_client", return_value=client):
        inv = sl.get_stations(s)
    assert _codes(inv) == ["GR.FUR.00.HHZ", "GR.FUR.00.LHZ", "GR.FUR.10.HHZ"]
    assert len(inv.networks) == 1 and len(inv[0].stations) == 1


def test_forced_station_with_no_matching_channels_is_dropped(capsys):
    s = _settings_for_force("00", "BH?")
    client, _ = _station_client(FDSNNoDataException("none"))
    with patch.object(sl, "make_client", return_value=client):
        assert sl.get_stations(s) is None
    assert "no channels match" in capsys.readouterr().out
