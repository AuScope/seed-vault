"""UI-agnostic geometry helpers shared by the Qt and (legacy) Streamlit front ends.

The map works in a Pacific-centred [0, 360) longitude window, so anything drawn
by the user is normalised into that window (and split if it crosses it).
"""
from typing import List

from seed_vault.models.common import RectangleArea, CircleArea
from seed_vault.models.config import GeometryConstraint

LON_RANGE_START = 0
LON_RANGE_END = 360


def lon_to_360(lon: float) -> float:
    return lon if lon >= 0 else lon + 360


def normalize_bounds(geometry_constraint: GeometryConstraint) -> List[GeometryConstraint]:
    """Split a rectangle crossing the active window boundary and normalise it into
    [LON_RANGE_START, LON_RANGE_END]."""
    rect = geometry_constraint.coords
    lat_min, lon_min = rect.min_lat, rect.min_lon
    lat_max, lon_max = rect.max_lat, rect.max_lon
    start_lon, end_lon = LON_RANGE_START, LON_RANGE_END

    def _rect(a, b):
        return GeometryConstraint(coords=RectangleArea(
            min_lat=lat_min, max_lat=lat_max, min_lon=a, max_lon=b, color=rect.color))

    if lon_min >= start_lon and lon_max <= end_lon:
        return [geometry_constraint]
    if lon_min < end_lon and lon_max > end_lon and lon_min >= start_lon:
        return [_rect(lon_min, end_lon), _rect(start_lon, lon_max - end_lon)]
    if lon_min < start_lon and start_lon <= lon_max <= end_lon:
        return [_rect(lon_min + end_lon, end_lon), _rect(start_lon, lon_max)]
    if lon_min < start_lon and lon_max < start_lon:
        return [_rect(lon_min + end_lon, lon_max + end_lon)]
    if lon_min > end_lon and lon_max > end_lon:
        return [_rect(lon_min - end_lon, lon_max - end_lon)]
    # A box wider than the whole window: just clamp it.
    return [_rect(start_lon, end_lon)]


def normalize_circle(geometry_constraint: GeometryConstraint) -> List[GeometryConstraint]:
    """Normalise a circle's centre longitude into [0, 360)."""
    c = geometry_constraint.coords
    return [GeometryConstraint(coords=CircleArea(
        lat=c.lat, lon=c.lon % 360, max_radius=c.max_radius,
        min_radius=c.min_radius, color=c.color))]


def is_valid_rectangle(min_lat, max_lat, min_lon, max_lon) -> bool:
    return (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and
            LON_RANGE_START <= min_lon <= LON_RANGE_END and
            LON_RANGE_START <= max_lon <= LON_RANGE_END and
            min_lat <= max_lat and min_lon <= max_lon)


def is_valid_circle(lat, lon, max_radius, min_radius) -> bool:
    return (-90 <= lat <= 90 and LON_RANGE_START <= lon <= LON_RANGE_END and
            max_radius > 0 and min_radius >= 0 and min_radius <= max_radius)


def unique_geo_constraints(geo_constraint_list) -> List[GeometryConstraint]:
    seen, unique = set(), []
    for gc in geo_constraint_list or []:
        try:
            key = tuple(sorted(gc.coords.model_dump().items()))
        except Exception:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(gc)
    return unique
