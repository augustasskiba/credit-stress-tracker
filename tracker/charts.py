"""Per-signal sparkline PNGs for the e-mail (Gmail strips SVG; inline PNG attachments render).

Each chart shows recent history as a neutral line, the amber/red zones from the signal's own
rule as light tinted bands, and a dot on the latest value in its status colour. Status is also
written as text in the table cell next to the chart, so the colour never carries meaning alone.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .rules import normalize_rule  # noqa: E402

# Status palette (good / warning / critical) and neutral inks
STATUS = {"green": "#0ca30c", "amber": "#fab219", "red": "#d03b3b", "stale": "#8a8980", "n/a": "#8a8980"}
LINE = "#52514a"
BASELINE = "#c3c2b7"
W_PX, H_PX, SCALE = 180, 40, 2       # CSS size in the e-mail; rendered at 2x for sharp screens


def _zones(rule: dict) -> dict:
    """Level thresholds that can be drawn as bands: {'amber': (op, value), 'red': (op, value)}."""
    out = {}
    r = normalize_rule(rule or {})
    for status in ("amber", "red"):
        for c in r.get(status, []):
            if "op" in c and "diff" not in c and "rising" not in c and c.get("value") is not None and abs(c["value"]) < 900:
                out[status] = (c["op"], float(c["value"]))
                break
    return out


def render(points: list, status: str, rule: dict, path: Path) -> bool:
    if not points or len(points) < 2:
        return False
    s = pd.Series([v for _, v in points], index=pd.to_datetime([d for d, _ in points]))
    lo, hi = float(s.min()), float(s.max())
    span = (hi - lo) or abs(hi) or 1.0
    zones = _zones(rule)
    # Pull a nearby threshold into view so the reader sees how close the line is to it
    for _, (op, v) in zones.items():
        if lo - 0.6 * span <= v <= hi + 0.6 * span:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.12 or 0.5
    y0, y1 = lo - pad, hi + pad

    fig = plt.figure(figsize=(W_PX / 100, H_PX / 100), dpi=100 * SCALE)
    ax = fig.add_axes([0.01, 0.06, 0.94, 0.88])
    for st in ("amber", "red"):
        if st not in zones:
            continue
        op, v = zones[st]
        if op in ("gt", "ge"):
            ax.axhspan(v, y1, color=STATUS[st], alpha=0.16 if st == "amber" else 0.20, lw=0)
        else:
            ax.axhspan(y0, v, color=STATUS[st], alpha=0.16 if st == "amber" else 0.20, lw=0)
        if y0 <= v <= y1:
            ax.axhline(v, color=STATUS[st], lw=0.8, alpha=0.9)
    dense = len(s) > 20
    ax.plot(s.index, s.values, color=LINE, lw=1.4 if dense else 1.2, solid_capstyle="round",
            marker=None if dense else "o", markersize=2.2)
    ax.plot([s.index[-1]], [s.values[-1]], "o", color=STATUS.get(status, LINE), markersize=5.5,
            markeredgecolor="white", markeredgewidth=1.2, zorder=5)
    ax.set_ylim(y0, y1)
    ax.set_xlim(s.index[0], s.index[-1] + (s.index[-1] - s.index[0]) * 0.04)
    ax.axis("off")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100 * SCALE, transparent=False, facecolor="white")
    plt.close(fig)
    return True


def render_all(results: list[dict], rules: dict[str, dict], out_dir: Path) -> list[dict]:
    """Render one PNG per signal with chart data. Returns [{id, path, sha256}] in table order."""
    out = []
    for r in results:
        p = out_dir / f"{r['id']}.png"
        if render(r.get("chart") or [], r["status"], rules.get(r["id"], {}), p):
            out.append({"id": r["id"], "path": str(p.resolve()),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return out
