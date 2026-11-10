"""Tests for the UI-independent helpers used by the desktop app."""
import pytest

from seed_vault.models.common import CircleArea, RectangleArea
from seed_vault.models.config import GeometryConstraint
from seed_vault.service import settings_store
from seed_vault.utils.geo import (is_valid_circle, is_valid_rectangle, normalize_bounds, normalize_circle,
                                  unique_geo_constraints)


@pytest.fixture(autouse=True)
def _no_client_csv_writes(monkeypatch):
    """UrlMappings.load() rewrites the packaged clients.csv; keep tests side-effect free."""
    from seed_vault.models.url_mapping import UrlMappings
    monkeypatch.setattr(UrlMappings, "load", lambda self: None)


def rect(a, b, c, d):
    return GeometryConstraint(coords=RectangleArea(min_lat=a, max_lat=b, min_lon=c, max_lon=d))


def lons(gcs):
    return sorted((g.coords.min_lon, g.coords.max_lon) for g in gcs)


@pytest.mark.parametrize("box, expected", [
    ((10, 20), [(10, 20)]),                       # inside window
    ((350, 380), [(0, 20), (350, 360)]),          # crosses 360 -> split
    ((-20, 10), [(0, 10), (340, 360)]),           # crosses 0 -> split
    ((-30, -10), [(330, 350)]),                   # fully negative -> shifted
    ((370, 380), [(10, 20)]),                     # fully > 360 -> shifted
])
def test_normalize_bounds(box, expected):
    assert lons(normalize_bounds(rect(-10, 10, *box))) == expected


def test_normalize_circle_wraps_longitude():
    gc = GeometryConstraint(coords=CircleArea(lat=5, lon=-20, min_radius=1, max_radius=3))
    (out,) = normalize_circle(gc)
    assert out.coords.lon == 340 and out.coords.min_radius == 1 and out.coords.max_radius == 3


def test_validators():
    assert is_valid_rectangle(-10, 10, 0, 360)
    assert not is_valid_rectangle(10, -10, 0, 10)
    assert not is_valid_rectangle(-10, 10, -5, 10)
    assert is_valid_circle(0, 180, 10, 0)
    assert not is_valid_circle(0, 180, 5, 10)


def test_unique_geo_constraints():
    a, b = rect(0, 1, 2, 3), rect(0, 1, 2, 3)
    assert len(unique_geo_constraints([a, b, rect(0, 1, 2, 4)])) == 2


def test_save_sections_preserves_other_sections(tmp_path):
    path = str(tmp_path / "config.cfg")
    base = settings_store.default_settings()
    base.db_path = "/archive/db.sqlite"
    base.event.min_magnitude = 3.0
    settings_store.save_settings(base, path)

    # A workflow changes the event filters, but holds a stale db_path
    wf = settings_store.load_settings(path)
    wf.event.min_magnitude = 6.5
    wf.db_path = "STALE"
    settings_store.save_sections(wf, settings_store.WORKFLOW_SECTIONS, path)

    on_disk = settings_store.load_settings(path)
    assert on_disk.event.min_magnitude == 6.5
    assert on_disk.db_path == "/archive/db.sqlite"

    # ...and refresh_sections pulls the current app sections into the workflow copy
    settings_store.refresh_sections(wf, settings_store.APP_SECTIONS, path)
    assert wf.db_path == "/archive/db.sqlite"


def test_render_config_roundtrip(tmp_path):
    path = str(tmp_path / "c.cfg")
    s = settings_store.default_settings()
    s.station.network = "AU"
    settings_store.save_settings(s, path)
    errors, _ = settings_store.validate_config_file(path)
    assert errors is None
    assert settings_store.load_settings(path).station.network == "AU"
