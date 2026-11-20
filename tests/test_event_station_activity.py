"""Events must only be kept/processed when a selected station was operating at origin time."""
import copy
from unittest.mock import patch

import numpy as np
import pytest
from obspy import UTCDateTime, read_inventory
from obspy.core.event import Catalog, Event, Origin

from seed_vault.enums.config import WorkflowType
from seed_vault.models.config import SeismoLoaderSettings
from seed_vault.service import seismoloader as sl


def _event(t, lat=48.0, lon=11.0):
    return Event(origins=[Origin(time=UTCDateTime(t), latitude=lat, longitude=lon, depth=10000)])


def _awkward_inventory():
    """Example inventory plus edge cases: closed channels in an open station,
    a closed network, and a station-level entry without channels."""
    inv = read_inventory()
    fur = inv.select(network="GR", station="FUR")[0][0]
    for c in fur:
        c.end_date = UTCDateTime("2009-01-01")           # station open-ended, channels closed
    extra = copy.deepcopy(inv.select(network="GR", station="WET")[0])
    extra.code, extra.end_date = "XX", UTCDateTime("2008-06-01")   # network closes before station/channels
    nochan = copy.deepcopy(inv.select(network="GR", station="WET")[0])
    nochan.code = "YY"
    nochan[0].channels = []
    nochan[0].start_date, nochan[0].end_date = UTCDateTime("2015-01-01"), UTCDateTime("2016-01-01")
    inv.networks += [extra, nochan]
    return inv


def test_intervals_match_obspy_select():
    inv = _awkward_inventory()
    iv = sl.station_activity_intervals(inv)
    rng = np.random.default_rng(0)
    times = rng.uniform(UTCDateTime("1999-01-01").timestamp, UTCDateTime("2020-01-01").timestamp, 1500)
    # include exact epoch boundaries
    times = np.concatenate([times, iv[np.isfinite(iv)].ravel()])
    for t in times:
        ours = bool(np.any((iv[:, 0] <= t) & (t <= iv[:, 1])))
        theirs = any(len(n.stations) for n in inv.select(time=UTCDateTime(t)))
        assert ours == theirs, UTCDateTime(t)


def test_filter_catalog_by_station_activity():
    inv = read_inventory()                                # earliest station starts 2001-05-15
    cat = Catalog(events=[_event("1995-01-01"), _event("2005-01-01"), _event("2012-01-01")])
    kept, removed = sl.filter_catalog_by_station_activity(cat, inv)
    assert removed == 1 and [str(e.origins[0].time)[:4] for e in kept] == ["2005", "2012"]
    same, n = sl.filter_catalog_by_station_activity(cat, None)
    assert same is cat and n == 0


@pytest.mark.parametrize("workflow, expected", [(WorkflowType.STATION_BASED, 2), (WorkflowType.EVENT_BASED, 3)])
def test_get_events_filters_only_in_station_based_flow(workflow, expected):
    s = SeismoLoaderSettings.create_default()
    s.selected_workflow = workflow
    s.station.selected_invs = read_inventory()
    cat = Catalog(events=[_event("1995-01-01"), _event("2005-01-01"), _event("2012-01-01")])
    with patch.object(sl, "_query_events", return_value=cat):
        assert len(sl.get_events(s)) == expected


def test_run_event_skips_events_without_operating_stations(tmp_path, capsys):
    s = SeismoLoaderSettings.create_default()
    s.sds_path, s.db_path = str(tmp_path / "sds"), str(tmp_path / "db.sqlite")
    s.station.selected_invs = read_inventory()
    s.event.selected_catalogs = Catalog(events=[_event("1995-01-01"), _event("2012-01-01")])
    with patch.object(sl, "make_client"), \
         patch.object(sl, "collect_requests_event", return_value=([], [], {})) as collect:
        sl.run_event(s, return_streams=False)
    assert collect.call_count == 1                         # only the 2012 event was processed
    assert "none of the selected stations were operating" in capsys.readouterr().out
