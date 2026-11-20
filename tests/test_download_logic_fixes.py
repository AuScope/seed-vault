"""Regression tests for download-pipeline and database fixes.

Each test reproduces a previously-wrong behaviour:
  1. events without a preferred origin shared one arrival-cache key
  2. arrivals were computed from origins[0] instead of the preferred origin
  3. continuous downloads with channel/location priorities dropped stations not
     active at the *end* of the range and ignored instrument changes
  4. location priority (given as a string) was ignored
  5. station-level credentials overwrote each other / were never used
  6. combined requests asked every station for every other station's channels
  7. a combine_requests failure re-sent the previous event's requests
  8. run_continuous reported "no requests" as success
  DB-1 a lock error inside a `with db.connection()` block became a RuntimeError
  DB-2 the multiprocessing fallback in populate_database_from_sds crashed
  DB-3 WITH/PRAGMA results were not returned by execute_query; blank query crashed
  DB-4 cached arrivals ignored the travel-time model
"""
import copy
import sqlite3
from unittest.mock import MagicMock, patch

import obspy
import pytest
from obspy import UTCDateTime as U, read_inventory
from obspy.core.event import Catalog, Event, Magnitude, Origin

from seed_vault.models.config import AuthConfig, SeismoLoaderSettings
from seed_vault.service import seismoloader as sl
from seed_vault.service.db import DatabaseManager, populate_database_from_sds


@pytest.fixture
def settings(tmp_path):
    s = SeismoLoaderSettings.create_default()
    s.sds_path, s.db_path = str(tmp_path / "sds"), str(tmp_path / "db.sqlite")
    s.event.min_radius, s.event.max_radius = 0, 180
    s.waveform.channel_pref, s.waveform.location_pref = "", ""
    s.station.highest_samplerate_only = False
    return s


def _fur():
    return read_inventory().select(network="GR", station="FUR")


def _station(chans, start=U("2010-01-01")):
    """GR.FUR rebuilt with channels [(loc, code, start, end), ...]."""
    inv = _fur()
    sta = inv[0][0]
    base = sta.channels[0]
    sta.channels = []
    for loc, code, c0, c1 in chans:
        c = copy.deepcopy(base)
        c.location_code, c.code, c.start_date, c.end_date = loc, code, c0, c1
        sta.channels.append(c)
    sta.start_date, sta.end_date = start, max((c[3] for c in chans if c[3]), default=None) \
        if all(c[3] for c in chans) else None
    return inv


def _event(t, preferred=True, origins=None, lat=40.0, lon=30.0):
    origins = origins or [Origin(time=U(t), latitude=lat, longitude=lon, depth=10000)]
    e = Event(origins=origins, magnitudes=[Magnitude(mag=6.0)])
    if preferred:
        e.preferred_origin_id = origins[-1].resource_id
    return e


def _windows(reqs):
    return sorted((r[2] or "--", r[3], r[4][:10], r[5][:10]) for r in reqs)


# --------------------------------------------------------------------- 1 & 2
def test_events_without_preferred_origin_get_their_own_arrivals(settings):
    inv = _fur()
    starts = []
    for t in ("2010-01-01", "2012-06-01"):
        ev = _event(t, preferred=False)
        reqs, arr, _ = sl.collect_requests_event(ev, inv, settings=settings)
        sl.setup_paths(settings)[1].bulk_insert_arrival_data(arr)
        starts.append(reqs[0][4][:10])
        assert sl.event_cache_key(ev) != "None"
    assert starts == ["2010-01-01", "2012-06-01"]


def test_preferred_origin_is_used_not_origins0(settings):
    other = Origin(time=U("2013-01-01T00:00:00"), latitude=-30, longitude=150, depth=10000)
    pref = Origin(time=U("2013-01-01T00:05:00"), latitude=40, longitude=30, depth=10000)
    ev = Event(origins=[other, pref], magnitudes=[Magnitude(mag=6.0)])
    ev.preferred_origin_id = pref.resource_id
    inv = _fur()
    _, arr, p = sl.collect_requests_event(ev, inv, settings=settings)
    sta = inv[0][0]
    assert arr[0][13] == pytest.approx(sl.locations2degrees(40, 30, sta.latitude, sta.longitude))
    assert arr[0][0] == str(pref.resource_id)
    assert U(list(p.values())[0]) > pref.time


def test_cache_key_unchanged_for_normal_events():
    ev = _event("2012-01-01")
    assert sl.event_cache_key(ev) == str(ev.preferred_origin_id)


def test_missing_depth_and_magnitude_do_not_crash(settings):
    ev = Event(origins=[Origin(time=U("2012-01-01"), latitude=40, longitude=30)])
    reqs, arr, _ = sl.collect_requests_event(ev, _fur(), settings=settings)
    assert reqs and arr[0][1] is None


# ------------------------------------------------------------------------- 3
def test_continuous_prefs_keep_station_that_closed_before_end():
    inv = _station([("", "HHZ", U("2010-01-01"), U("2015-01-01"))])
    reqs = sl.collect_requests(inv, U("2014-01-01"), U("2016-01-01"), days_per_request=1000, cha_pref="HH")
    assert _windows(reqs) == [("--", "HHZ", "2014-01-01", "2015-01-01")]


def test_continuous_prefs_follow_instrument_change():
    inv = _station([("", "HHZ", U("2010-01-01"), U("2015-01-01")),
                    ("", "BHZ", U("2015-01-01"), None)])
    reqs = sl.collect_requests(inv, U("2014-01-01"), U("2016-01-01"), days_per_request=1000,
                               cha_pref="HH,BH")
    assert _windows(reqs) == [("--", "BHZ", "2015-01-01", "2016-01-01"),
                              ("--", "HHZ", "2014-01-01", "2015-01-01")]


def test_continuous_without_prefs_unchanged():
    inv = _station([("", "HHZ", U("2010-01-01"), U("2015-01-01")), ("", "BHZ", U("2010-01-01"), None)])
    reqs = sl.collect_requests(inv, U("2014-01-01"), U("2016-01-01"), days_per_request=1000)
    assert _windows(reqs) == [("--", "BHZ", "2014-01-01", "2016-01-01"),
                              ("--", "HHZ", "2014-01-01", "2015-01-01")]


# ------------------------------------------------------------------------- 4
@pytest.mark.parametrize("loc_pref, expected", [("10,00", "10"), ("00,10", "00"), ("--,00", "--")])
def test_location_priority_from_string(loc_pref, expected):
    other = "00" if expected != "00" else "10"
    first = "" if expected == "--" else expected
    inv = _station([(other if expected != "--" else "00", "BHZ", U("2010-01-01"), None),
                    (first, "BHZ", U("2010-01-01"), None)])
    out = sl.get_preferred_channels(inv, "BH", loc_pref)
    assert [c.location_code or "--" for c in out[0][0]] == [expected]


@pytest.mark.parametrize("cha_pref, expected", [("HH?,BH?", "HHZ"), ("BH1,BHZ,HH?", "BHZ"), ("BH,HH", "BHZ")])
def test_channel_priority_patterns(cha_pref, expected):
    inv = _station([("", "HHZ", U("2010-01-01"), None), ("", "BHZ", U("2010-01-01"), None)])
    out = sl.get_preferred_channels(inv, cha_pref, None)
    assert [c.code for c in out[0][0]] == [expected]


def test_parse_pref_list():
    assert sl.parse_pref_list(" HH, BH ,,EH ") == ["HH", "BH", "EH"]
    assert sl.parse_pref_list("") is None and sl.parse_pref_list(None) is None
    assert sl.parse_pref_list(["00", "--"]) == ["00", "--"]


# ------------------------------------------------------------------------- 5
def test_station_level_credentials_each_get_their_own_client(settings):
    settings.auths = [AuthConfig(nslc_code="XX.AAA", username="a", password="pa"),
                      AuthConfig(nslc_code="XX.BBB", username="b", password="pb"),
                      AuthConfig(nslc_code="YY", username="y", password="py")]
    made = []
    with patch.object(sl, "make_client", side_effect=lambda *a, **k: made.append(k["user"]) or k["user"]):
        clients = sl.build_waveform_clients(settings, "OPEN", ["XX", "YY"])
    assert made == ["a", "b", "y"]
    assert sl.client_for_station(clients, "XX", "AAA") == "a"
    assert sl.client_for_station(clients, "XX", "BBB") == "b"
    assert sl.client_for_station(clients, "XX", "CCC") == "OPEN"
    assert sl.client_for_station(clients, "YY", "ANY") == "y"


def test_archive_request_uses_per_station_clients(settings):
    def fake(name):
        c = MagicMock(name=name)
        c.services = {"dataselect": {}}
        c.get_waveforms.return_value = obspy.Stream()
        return c
    clients = {"open": fake("open"), "XX.AAA": fake("a"), "XX.BBB": fake("b")}
    db = sl.setup_paths(settings)[1]
    sl.archive_request(("XX", "AAA,BBB,CCC", "", "BHZ", "2020-01-01T00:00:00", "2020-01-01T01:00:00"),
                       clients, settings.sds_path, db)
    called = {k: [c.kwargs["station"] for c in v.get_waveforms.call_args_list] for k, v in clients.items()}
    assert called == {"open": ["CCC"], "XX.AAA": ["AAA"], "XX.BBB": ["BBB"]}


# ------------------------------------------------------------------------- 6
def test_combine_requests_does_not_cross_channels():
    t0, t1 = "2020-01-01T00:00:00", "2020-01-02T00:00:00"
    reqs = [("XX", "AAA", "00", "HHZ", t0, t1), ("XX", "BBB", "10", "BHZ", t0, t1),
            ("XX", "CCC", "00", "HHZ", t0, t1), ("XX", "CCC", "00", "HHN", t0, t1),
            ("XX", "DDD", "00", "HHZ", t0, t1)]
    out = sorted(sl.combine_requests(reqs))
    assert out == [("XX", "AAA,DDD", "00", "HHZ", t0, t1),
                   ("XX", "BBB", "10", "BHZ", t0, t1),
                   ("XX", "CCC", "00", "HHN,HHZ", t0, t1)]
    # every requested (station, loc, channel) is covered, and nothing extra
    asked = {(s, r[2], c) for r in out for s in r[1].split(",") for c in r[3].split(",")}
    assert asked == {(r[1], r[2], r[3]) for r in reqs}


# ------------------------------------------------------------------------- 7
def test_combine_failure_does_not_resend_previous_event(settings):
    settings.station.selected_invs = _fur()
    settings.event.selected_catalogs = Catalog(events=[_event("2012-01-01"), _event("2012-02-01")])
    req = lambda d: [("GR", "FUR", "", "BHZ", f"{d}T00:00:00", f"{d}T00:10:00")]  # noqa: E731
    sent = []
    with patch.object(sl, "make_client"), \
         patch.object(sl, "collect_requests_event", side_effect=[(req("2012-01-01"), [], {}),
                                                                 (req("2012-02-01"), [], {})]), \
         patch.object(sl, "prune_requests", side_effect=lambda r, *a: r), \
         patch.object(sl, "combine_requests", side_effect=[req("2012-01-01"), ValueError("boom")]), \
         patch.object(sl, "archive_request", side_effect=lambda r, *a: sent.append(r[4][:10])):
        sl.run_event(settings, return_streams=False)
    assert sent == ["2012-01-01"]


# ------------------------------------------------------------------------- 8
def test_run_continuous_reports_no_requests_as_failure(settings):
    settings.station.selected_invs = _station([("", "HHZ", U("2010-01-01"), U("2011-01-01"))])
    settings.station.date_config.start_time = U("2014-01-01").datetime
    settings.station.date_config.end_time = U("2015-01-01").datetime
    with patch.object(sl, "make_client"):
        assert sl.run_continuous(settings) is False


# ---------------------------------------------------------------------- DB-1
def test_lock_error_inside_block_is_raised_cleanly_and_rolled_back(tmp_path):
    db = DatabaseManager(str(tmp_path / "db.sqlite"))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        with db.connection(initial_delay=0.01) as conn:
            conn.execute("INSERT INTO archive_data (network) VALUES ('ZZ')")
            raise sqlite3.OperationalError("database is locked")
    assert db.execute_query("SELECT COUNT(*) n FROM archive_data")[2].n[0] == 0
    with db.connection() as conn:
        conn.execute("INSERT INTO archive_data (network) VALUES ('ZZ')")
    assert db.execute_query("SELECT COUNT(*) n FROM archive_data")[2].n[0] == 1


def test_connection_retries_when_opening_is_locked(tmp_path):
    db = DatabaseManager(str(tmp_path / "db.sqlite"))
    real = sqlite3.connect
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)
    with patch("seed_vault.service.db.sqlite3.connect", side_effect=flaky), \
         patch("seed_vault.service.db.sleep"):
        with db.connection() as conn:
            conn.execute("SELECT 1")
    assert len(calls) == 2


# ---------------------------------------------------------------------- DB-2
def test_sds_sync_falls_back_to_single_process(tmp_path):
    day = tmp_path / "sds" / "2009" / "BW" / "RJOB" / "EHZ.D"
    day.mkdir(parents=True)
    obspy.read().select(channel="EHZ").write(str(day / "BW.RJOB..EHZ.D.2009.236"), format="MSEED")

    class BrokenPool:
        def __init__(self, *a, **k):
            raise OSError("cannot fork")
    with patch("seed_vault.service.db.multiprocessing.Pool", BrokenPool):
        populate_database_from_sds(str(tmp_path / "sds"), str(tmp_path / "db.sqlite"), num_processes=4)
    df = DatabaseManager(str(tmp_path / "db.sqlite")).execute_query("SELECT * FROM archive_data")[2]
    assert list(df.station) == ["RJOB"]


# ---------------------------------------------------------------------- DB-3
@pytest.mark.parametrize("query, n_rows", [
    ("SELECT 1 AS a", 1),
    ("with x as (select 1 as a union select 2) select a from x", 2),
    ("PRAGMA table_info(archive_data)", 8),
])
def test_execute_query_returns_rows_for_any_row_statement(tmp_path, query, n_rows):
    err, msg, df = DatabaseManager(str(tmp_path / "db.sqlite")).execute_query(query)
    assert not err and len(df) == n_rows, msg


def test_execute_query_blank_and_modify(tmp_path):
    db = DatabaseManager(str(tmp_path / "db.sqlite"))
    assert db.execute_query("   ")[0] is True
    err, msg, df = db.execute_query("INSERT INTO archive_data (network) VALUES ('ZZ')")
    assert not err and df is None and "Rows affected: 1" in msg


# ---------------------------------------------------------------------- DB-4
def test_arrival_cache_respects_model(settings):
    ev, inv = _event("2012-01-01"), _fur()
    settings.event.model = "iasp91"
    _, arr, _ = sl.collect_requests_event(ev, inv, settings=settings)
    db = sl.setup_paths(settings)[1]
    db.bulk_insert_arrival_data(arr)
    key = sl.event_cache_key(ev)
    assert db.fetch_arrivals_distances(key, "GR", "FUR", model="IASP91") is not None
    assert db.fetch_arrivals_distances(key, "GR", "FUR", model="ak135") is None
    assert db.fetch_arrivals_distances(key, "GR", "FUR") is not None       # unfiltered still works
    settings.event.model = "ak135"
    _, arr2, _ = sl.collect_requests_event(ev, inv, settings=settings)
    assert arr2, "a different model must recompute arrivals instead of reusing the cache"
