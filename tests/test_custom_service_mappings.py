"""Custom per-service client URLs, exercised against a local fake FDSN server."""
import io
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import obspy
import pytest
from obspy import read_events, read_inventory

from seed_vault.models import url_mapping
from seed_vault.models.url_mapping import UrlMappings
from seed_vault.service import fdsn_client
from seed_vault.service.fdsn_client import MappedClient, make_client, service_mappings_from_row


def _payloads():
    cat, inv, st = io.BytesIO(), io.BytesIO(), io.BytesIO()
    read_events().write(cat, format="QUAKEML")
    read_inventory().write(inv, format="STATIONXML")
    obspy.read().write(st, format="MSEED")
    return {"/custom/quakes/1/query": (cat.getvalue(), "application/xml"),
            "/api/stations/v2/query": (inv.getvalue(), "application/xml"),
            "/wf/1/query": (st.getvalue(), "application/vnd.fdsn.mseed")}


@pytest.fixture(scope="module")
def fake_server():
    routes = _payloads()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            hits.append(path)
            if path in routes:                       # note: no application.wadl anywhere
                body, ctype = routes[path]
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    srv.shutdown()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def clients_csv(tmp_path, monkeypatch):
    """Point clients.csv at a temp copy so the packaged file is untouched."""
    path = tmp_path / "clients.csv"
    monkeypatch.setattr(url_mapping, "CLIENTS_CSV_PATH", str(path))
    assert str(UrlMappings().save_path) == str(path)
    return path


def test_row_parsing():
    row = {"client": "X", "url": "", "dataselect": "https://a/wf/1/", "event": "none", "station": ""}
    assert service_mappings_from_row(row) == {"dataselect": "https://a/wf/1", "event": None}
    assert fdsn_client.base_url_for("", {"dataselect": "https://a.org/wf/1"}) == "https://a.org"


def test_old_csv_without_service_columns_still_loads(clients_csv):
    clients_csv.write_text("client,url,is_original\nMINE,https://example.org,false\n")
    m = UrlMappings()
    details = m.get_extra_client_details()
    assert details == [{"client": "MINE", "url": "https://example.org", "dataselect": "", "event": "", "station": ""}]
    assert "dataselect" in clients_csv.read_text().splitlines()[0]


def test_custom_service_urls_end_to_end(fake_server, clients_csv):
    base, hits = fake_server
    UrlMappings().save([{"client": "MYTEST", "url": "",
                         "event": f"{base}/custom/quakes/1",
                         "station": f"{base}/api/stations/v2",
                         "dataselect": f"{base}/wf/1"}])
    m = UrlMappings()
    assert "MYTEST" in m.get_clients()
    assert m.get_extra_client_details()[0]["event"] == f"{base}/custom/quakes/1"

    c = make_client("MYTEST")
    assert isinstance(c, MappedClient)
    # no WADLs were published, but the configured services are trusted
    assert set(c.services) >= {"event", "station", "dataselect"}

    cat = c.get_events(starttime=obspy.UTCDateTime(2012, 1, 1), endtime=obspy.UTCDateTime(2013, 1, 1))
    inv = c.get_stations(network="*")
    st = c.get_waveforms("BW", "RJOB", "", "EH?", obspy.UTCDateTime(2009, 8, 24, 0, 20, 3),
                         obspy.UTCDateTime(2009, 8, 24, 0, 20, 30))
    assert len(cat) == 3 and len(inv.get_contents()["stations"]) > 0 and len(st) == 3
    for path in ("/custom/quakes/1/query", "/api/stations/v2/query", "/wf/1/query"):
        assert path in hits

    # the backend's own entry points use the mapping too
    from seed_vault.service.utils import check_client_services
    assert check_client_services("MYTEST") == {"station": True, "event": True, "dataselect": True}


def test_disabled_service_and_standard_fallback(fake_server, clients_csv):
    base, _ = fake_server
    UrlMappings().save([{"client": "PARTIAL", "url": base, "event": "none",
                         "station": f"{base}/api/stations/v2", "dataselect": ""}])
    c = make_client("PARTIAL")
    assert "event" not in c.services                      # explicitly disabled
    assert "station" in c.services                        # custom URL
    assert c._build_url("dataselect", "query") == f"{base}/fdsnws/dataselect/1/query"   # standard path


def test_plain_extra_client_and_builtin_unchanged(clients_csv):
    UrlMappings().save([{"client": "PLAIN", "url": "https://example.org"}])
    row = fdsn_client._client_row("PLAIN")
    assert row["url"] == "https://example.org" and not service_mappings_from_row(row)
    # built-in shortcuts still go straight to ObsPy (no network: skip discovery)
    c = make_client("GEOFON", _discover_services=False)
    assert type(c).__name__ == "Client" and "geofon" in c.base_url


def test_saving_without_service_keys_keeps_mappings(clients_csv):
    """Callers that only pass {client, url} (legacy web UI) must not wipe service URLs."""
    UrlMappings().save([{"client": "KEEP", "url": "https://a.org", "event": "https://b.org/ev/1"}])
    UrlMappings().save([{"client": "KEEP", "url": "https://a2.org"}])
    (d,) = UrlMappings().get_extra_client_details()
    assert d["url"] == "https://a2.org" and d["event"] == "https://b.org/ev/1"
