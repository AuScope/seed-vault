"""Trace processing and plotting for event arrivals (toolkit-independent).

Ported from ``seed_vault.ui.components.waveform.WaveformDisplay`` but using
``matplotlib.figure.Figure`` directly, so figures aren't registered with pyplot
(no leaks, safe to embed in Qt).
"""
from typing import Dict, Optional, Tuple

import numpy as np
from matplotlib.figure import Figure
from obspy import Stream, UTCDateTime

from seed_vault.models.config import SeismoLoaderSettings


def get_tele_filter(tr) -> Tuple[float, float]:
    """Distance-dependent bandpass corners (Hz); (0, 0) for non-seismic sensors."""
    distance_km = getattr(tr.stats, "distance_km", 99999) or 99999
    nyq = tr.stats.sampling_rate / 2 - 0.02
    if tr.stats.channel[1:2] not in ("H", "N", "P", "D"):
        return 0, 0
    for limit, band in ((50, (2.0, 15)), (100, (1.7, 12)), (250, (1.5, 10)), (500, (1.4, 8)),
                        (1000, (1.3, 6)), (2500, (1.2, 5)), (5000, (1.0, 3)), (10000, (0.8, 2))):
        if distance_km < limit:
            f0, f1 = band
            break
    else:
        f0, f1 = 0.6, 1.5
    return min(f0, nyq), min(f1, nyq)


def trace_color(tr) -> str:
    comp = tr.stats.channel[-1:].upper()
    sens = tr.stats.channel[1:2].upper()
    if sens not in ("H", "N", "P"):
        return "tomato"
    if comp == "Z":
        return "black"
    if comp in ("N", "1"):
        return "darkblue" if sens == "H" else "blue"
    if comp in ("E", "2"):
        return "darkgreen" if sens == "H" else "green"
    return "gray"


class TraceProcessor:
    """Detrend/taper/(response removal)/window/filter with a per-trace cache."""

    def __init__(self, settings: SeismoLoaderSettings):
        self.settings = settings
        self._cache: Dict[str, object] = {}

    def clear(self):
        self._cache.clear()

    def _key(self, tr, fmin, fmax) -> str:
        s = self.settings
        tid = f"{tr.id}_{tr.stats.starttime}"
        return f"{tid}_{s.station.level}_{fmin}_{fmax}_{s.event.before_p_sec}_{s.event.after_p_sec}"

    def process(self, tr, fmin: float, fmax: float):
        key = self._key(tr, fmin, fmax)
        if key in self._cache:
            return self._cache[key]
        out = tr.copy()
        out.detrend()
        if str(getattr(self.settings.station.level, "value", self.settings.station.level)) == "response":
            out.taper(0.1)
            try:
                out.remove_response(self.settings.station.selected_invs, pre_filt=[0.08, 0.2, 30, 49])
                out.stats.plotunit = "VELOCITY (inst. response removed)"
            except Exception:
                print(f"WARNING: Could not remove response for {tr.stats.network}.{tr.stats.station}")
                out.stats.plotunit = "COUNTS"
        else:
            out.taper(0.03)
            out.stats.plotunit = "COUNTS"
        if hasattr(tr.stats, "p_arrival"):
            p = UTCDateTime(tr.stats.p_arrival)
            out = out.slice(p - self.settings.event.before_p_sec, p + self.settings.event.after_p_sec)
        if out.stats.sampling_rate / 2 > fmin and fmin < fmax:
            out.filter("bandpass", freqmin=fmin, freqmax=fmax, zerophase=True)
        out.stats.filterband = (fmin, fmax)
        self._cache[key] = out
        return out


def _label(tr, processed, mode: str) -> str:
    base = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location or ''}.{tr.stats.channel}"
    info = []
    if hasattr(tr.stats, "distance_km"):
        info.append(f"{tr.stats.distance_km:.1f} km")
    if hasattr(tr.stats, "event_time"):
        info.append(f"OT:{str(tr.stats.event_time)[0:19]}")
    if hasattr(tr.stats, "event_magnitude"):
        info.append(f"M{tr.stats.event_magnitude:.1f}")
    if hasattr(tr.stats, "event_region"):
        info.append(str(tr.stats.event_region))
    if hasattr(processed.stats, "filterband"):
        info.append(f"{processed.stats.filterband[0]}-{processed.stats.filterband[1]}Hz")
    if hasattr(processed.stats, "plotunit"):
        info.append(processed.stats.plotunit)
    return f"{base} - {', '.join(info)}"


def plot_traces(stream: Stream, settings: SeismoLoaderSettings, processor: TraceProcessor,
                mode: str = "event", width_in: float = 12.0) -> Optional[Figure]:
    """One panel per trace, aligned on the predicted P arrival (t = 0)."""
    if not stream:
        return None
    n = len(stream)
    height = max(4.0, n * 1.0 + 0.5)
    fig = Figure(figsize=(width_in, height))
    gs = fig.add_gridspec(n, 1, hspace=0.05, top=1 - 0.3 / height, bottom=0.6 / height, left=0.04, right=0.98)
    before_p, after_p = settings.event.before_p_sec, settings.event.after_p_sec
    axes = []
    last_p = None
    for i, tr in enumerate(stream):
        ax = fig.add_subplot(gs[i], sharex=axes[0] if axes else None)
        axes.append(ax)
        fmin, fmax = get_tele_filter(tr)
        try:
            proc = processor.process(tr, fmin, fmax)
        except Exception as e:  # noqa: BLE001
            ax.text(0.5, 0.5, f"{tr.id}: could not process ({e})", transform=ax.transAxes,
                    ha="center", va="center", fontsize=7, color="#b00020")
            ax.set_yticks([])
            continue
        if hasattr(tr.stats, "p_arrival"):
            last_p = UTCDateTime(tr.stats.p_arrival)
            t = np.arange(proc.stats.npts) * proc.stats.delta + (proc.stats.starttime - last_p)
        else:
            t = np.arange(proc.stats.npts) * proc.stats.delta - before_p
        ax.plot(t, proc.data, "-", color=trace_color(tr), linewidth=0.8)
        ax.axvline(0, color="red", linewidth=1, alpha=0.8)
        ax.text(0.01, 0.95, _label(tr, proc, mode), transform=ax.transAxes, va="top", ha="left", fontsize=7,
                bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", pad=1))
        ax.set_yticks([])
        ax.grid(True, alpha=0.2)
        for sp in ax.spines.values():
            sp.set_linewidth(0.5)
        if i < n - 1:
            ax.tick_params(labelbottom=False)
    axes[0].set_xlim(-before_p, after_p)
    axes[-1].set_xlabel("Seconds relative to P" + (f" ({last_p})" if (last_p and mode == "event") else ""))
    return fig
