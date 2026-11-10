"""Leaflet map embedded in Qt (QWebEngineView + QWebChannel).

Python pushes markers/areas into the page with small JSON calls; the page
reports drawn shapes, marker clicks and view changes back through ``_Bridge``.
"""
import base64
import html
import json
import os
import re
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.colors as mcolors
from obspy.geodetics import degrees2kilometers, kilometer2degrees
from PySide6.QtCore import QCoreApplication, QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from seed_vault.enums.ui import Steps
from seed_vault.models.common import CircleArea, RectangleArea
from seed_vault.models.config import GeometryConstraint
from seed_vault.utils.constants import AREA_COLOR
from seed_vault.utils.geo import lon_to_360, normalize_bounds, normalize_circle

RESOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
# The page is given this origin so tile servers receive a meaningful Referer
# (OSM's tile policy requires one). Every asset is inlined, so nothing is
# actually fetched from it.
PAGE_ORIGIN = "https://auscope.github.io/seed-vault/"

DEPTH_VMIN, DEPTH_VMAX = -5.0, 500.0
MAX_LEGEND_CATEGORIES = 15


# ----------------------------------------------------------------------------
# Network plumbing
# ----------------------------------------------------------------------------
_profile: Optional[QWebEngineProfile] = None


def _shared_profile() -> QWebEngineProfile:
    global _profile
    if _profile is None:
        # Parented to the application so it outlives every page using it.
        _profile = QWebEngineProfile("seed-vault-map", QCoreApplication.instance())  # persistent tile cache
        _profile.setHttpUserAgent(_profile.httpUserAgent() + " SEED-Vault")
    return _profile


_page_html: Optional[str] = None


def _data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".")
    mime = {"png": "image/png", "svg": "image/svg+xml"}.get(ext, "application/octet-stream")
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"


def _inline_css(path: str) -> str:
    css = open(path, encoding="utf-8").read()
    img_dir = os.path.join(os.path.dirname(path), "images")

    def repl(m):
        name = m.group(1).strip("'\"")
        if name.startswith("images/"):
            return f"url('{_data_uri(os.path.join(img_dir, name[len('images/'):]))}')"
        return m.group(0)
    return re.sub(r"url\(([^)]*)\)", repl, css)


def page_html() -> str:
    """map.html with Leaflet, Leaflet.draw and qwebchannel.js inlined."""
    global _page_html
    if _page_html is None:
        lf = os.path.join(RESOURCE_DIR, "leaflet")
        qf = QFile(":/qtwebchannel/qwebchannel.js")
        qf.open(QIODevice.ReadOnly)
        qwc = bytes(qf.readAll()).decode("utf-8")
        qf.close()
        html_src = open(os.path.join(RESOURCE_DIR, "map.html"), encoding="utf-8").read()
        for key, val in {
            "/*LEAFLET_CSS*/": _inline_css(os.path.join(lf, "leaflet.css")),
            "/*LEAFLET_DRAW_CSS*/": _inline_css(os.path.join(lf, "leaflet.draw.css")),
            "/*LEAFLET_JS*/": open(os.path.join(lf, "leaflet.js"), encoding="utf-8").read(),
            "/*LEAFLET_DRAW_JS*/": open(os.path.join(lf, "leaflet.draw.js"), encoding="utf-8").read(),
            "/*QWEBCHANNEL_JS*/": qwc,
        }.items():
            html_src = html_src.replace(key, val.replace("</script", "<\\/script"))
        _page_html = html_src
    return _page_html


class _Bridge(QObject):
    readySig = Signal()
    drawCreatedSig = Signal(dict)
    markerClickedSig = Signal(str, int)
    viewChangedSig = Signal(float, float, int)

    @Slot()
    def ready(self):
        self.readySig.emit()

    @Slot(str)
    def drawCreated(self, payload):
        try:
            self.drawCreatedSig.emit(json.loads(payload))
        except Exception:
            pass

    @Slot(str, int)
    def markerClicked(self, layer, marker_id):
        self.markerClickedSig.emit(layer, marker_id)

    @Slot(float, float, int)
    def viewChanged(self, lat, lng, zoom):
        self.viewChangedSig.emit(lat, lng, zoom)


# ----------------------------------------------------------------------------
# Marker styling (ported from the folium implementation)
# ----------------------------------------------------------------------------
def event_marker_radius(mag: float) -> float:
    if mag is None or (isinstance(mag, float) and np.isnan(mag)):
        return 5
    if mag < 2:
        r = 0.5
    elif mag < 3:
        r = 1.0
    elif mag < 4:
        r = 1.5
    elif mag <= 5:
        r = 2.0
    elif mag >= 8:
        r = 18.0
    else:
        x = (mag - 5) / 3
        r = 2 + 16 * x ** 2
    return float(np.clip(r, 5, 15))


def depth_colors(depths) -> List[str]:
    norm = mcolors.Normalize(vmin=DEPTH_VMIN, vmax=DEPTH_VMAX)
    rgba = mpl.colormaps["inferno_r"](norm(np.asarray(depths, dtype=float)))
    return [mcolors.rgb2hex(c[:3]) for c in rgba]


def category_colors(values) -> Dict[str, str]:
    cats = list(pd.unique(pd.Series(values).astype(str)))
    n = min(len(cats), MAX_LEGEND_CATEGORIES + 1) or 1
    cmap = mpl.colormaps["tab10"].resampled(n)
    return {c: mcolors.rgb2hex(cmap(i % n)[:3]) for i, c in enumerate(cats)}


def depth_legend_html() -> str:
    """Vertical colour bar: rotated title on the left, ticks on the right (shallow at top)."""
    stops = ", ".join(mcolors.rgb2hex(mpl.colormaps["inferno_r"](x)[:3]) for x in np.linspace(0, 1, 12))
    ticks = "".join(
        f'<div style="top:{100 * (v - DEPTH_VMIN) / (DEPTH_VMAX - DEPTH_VMIN):.1f}%">{v:g}</div>'
        for v in (0, 100, 200, 300, 400, 500))
    return ('<div class="cbar"><div class="title">Depth (km)</div>'
            f'<div class="bar" style="background:linear-gradient(to bottom, {stops})"></div>'
            f'<div class="ticks">{ticks}</div></div>')


def category_legend_html(title: str, cmap: Dict[str, str]) -> str:
    items = list(cmap.items())
    rows = [f'<div><span class="sw" style="background:{c}"></span>{html.escape(k)}</div>'
            for k, c in items[:MAX_LEGEND_CATEGORIES]]
    if len(items) > MAX_LEGEND_CATEGORIES:
        rows.append(f"<div>… +{len(items) - MAX_LEGEND_CATEGORIES} more</div>")
    return f"<b>{html.escape(title)}</b>" + "".join(rows)


def _popup_table(row: pd.Series, title: str, skip=("is_selected",)) -> str:
    cells = "".join(
        f"<tr><td><b>{html.escape(str(k))}</b></td><td>{html.escape(_fmt(v))}</td></tr>"
        for k, v in row.items() if k not in skip)
    return f'<div class="sv-popup"><h4>{html.escape(title)}</h4><table>{cells}</table></div>'


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def build_markers(df: pd.DataFrame, step: Steps, selected: Optional[set] = None):
    """Return (markers, legend_html) for an event or station DataFrame.
    Marker ids are the DataFrame's positional row numbers."""
    selected = selected or set()
    if df is None or df.empty:
        return [], ""
    markers = []
    if step == Steps.EVENT:
        colors = depth_colors(df["depth (km)"].to_numpy())
        legend = depth_legend_html()
        for pos, (label, row) in enumerate(df.iterrows()):
            place = str(row.get("place", ""))
            mag = row.get("magnitude")
            tip = f"M{mag:.1f} {row.get('magnitude type', '')} — {place[:50]}<br>{row.get('time')}"
            markers.append({
                "id": pos, "lat": float(row["latitude"]), "lon": lon_to_360(float(row["longitude"])),
                "color": colors[pos], "r": event_marker_radius(mag), "sel": label in selected,
                "shape": "circle", "tip": tip, "popup": _popup_table(row, place)})
    else:
        cmap = category_colors(df["network"])
        legend = category_legend_html("Network", cmap)
        for pos, (label, row) in enumerate(df.iterrows()):
            code = f"{row['network']}.{row['station']}"
            tip = f"{code} — {html.escape(str(row.get('description', '')))[:50]}"
            markers.append({
                "id": pos, "lat": float(row["latitude"]), "lon": lon_to_360(float(row["longitude"])),
                "color": cmap[str(row["network"])], "r": 7, "sel": label in selected,
                "shape": "tri", "tip": tip, "popup": _popup_table(row, code)})
    return markers, legend


def build_prev_markers(df: pd.DataFrame, step: Steps):
    """Markers for the previous step's selection (always drawn 'selected', no legend)."""
    if df is None or df.empty:
        return []
    m, _ = build_markers(df, step, selected=set(df.index))
    for x in m:
        x["fo"] = 0.9
    return m


def areas_to_js(geo_constraints: List[GeometryConstraint]) -> List[dict]:
    out = []
    for gc in geo_constraints or []:
        c = gc.coords
        if isinstance(c, RectangleArea):
            out.append({"type": "rect", "min_lat": c.min_lat, "max_lat": c.max_lat,
                        "min_lon": c.min_lon, "max_lon": c.max_lon, "color": c.color or AREA_COLOR})
        elif isinstance(c, CircleArea):
            out.append({"type": "circle", "lat": c.lat, "lon": c.lon,
                        "min_r_m": degrees2kilometers(c.min_radius or 0) * 1000,
                        "max_r_m": degrees2kilometers(c.max_radius) * 1000,
                        "color": c.color or AREA_COLOR})
    return out


def drawing_to_constraints(g: dict) -> List[GeometryConstraint]:
    """Convert a Leaflet.draw payload to normalised GeometryConstraints."""
    if g.get("type") == "rectangle":
        gc = GeometryConstraint(coords=RectangleArea(
            min_lat=max(-90.0, g["south"]), max_lat=min(90.0, g["north"]),
            min_lon=g["west"], max_lon=g["east"]))
        return normalize_bounds(gc)
    if g.get("type") == "circle":
        gc = GeometryConstraint(coords=CircleArea(
            lat=g["lat"], lon=g["lng"], min_radius=0,
            max_radius=kilometer2degrees(g["radius_m"] / 1000.0)))
        return normalize_circle(gc)
    return []


# ----------------------------------------------------------------------------
# Widget
# ----------------------------------------------------------------------------
class MapWidget(QWidget):
    drawCreated = Signal(list)           # list[GeometryConstraint]
    markerClicked = Signal(str, int)     # layer ('main'|'prev'), positional id
    viewChanged = Signal(float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView(self)
        page = QWebEnginePage(_shared_profile(), self.view)
        self.view.setPage(page)

        self._bridge = _Bridge()
        self._channel = QWebChannel(page)
        self._channel.registerObject("bridge", self._bridge)
        page.setWebChannel(self._channel)

        self._ready = False
        self._queue: List[str] = []
        self.center = (-20.0, 180.0)
        self.zoom = 2

        self._bridge.readySig.connect(self._on_ready)
        self._bridge.drawCreatedSig.connect(lambda g: self.drawCreated.emit(drawing_to_constraints(g)))
        self._bridge.markerClickedSig.connect(self.markerClicked)
        self._bridge.viewChangedSig.connect(self._on_view_changed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        self.view.setHtml(page_html(), QUrl(PAGE_ORIGIN))

    # -- plumbing ---------------------------------------------------------
    def _on_ready(self):
        self._ready = True
        for js in self._queue:
            self.view.page().runJavaScript(js)
        self._queue.clear()

    def _on_view_changed(self, lat, lng, zoom):
        self.center, self.zoom = (lat, lng), zoom
        self.viewChanged.emit(lat, lng, zoom)

    def _call(self, fn: str, *args):
        js = f"SV.{fn}({', '.join(json.dumps(a, default=str) for a in args)});"
        if self._ready:
            self.view.page().runJavaScript(js)
        else:
            self._queue.append(js)

    def is_ready(self) -> bool:
        return self._ready

    # -- public API -------------------------------------------------------
    def set_markers(self, markers: List[dict], legend_html: str = ""):
        self._call("setMarkers", markers)
        self._call("setLegend", legend_html)

    def set_prev_markers(self, markers: List[dict]):
        self._call("setPrevMarkers", markers)

    def set_selected(self, ids: List[int]):
        self._call("setSelected", [int(i) for i in ids])

    def set_areas(self, geo_constraints: List[GeometryConstraint]):
        self._call("setAreas", areas_to_js(geo_constraints))

    def set_view(self, lat: float, lng: float, zoom: int):
        self.center, self.zoom = (lat, lng), zoom
        self._call("setView", lat, lng, zoom)

    def fit_markers(self):
        self._call("fitMarkers")

    def open_popup(self, marker_id: int):
        self._call("openPopup", int(marker_id))
