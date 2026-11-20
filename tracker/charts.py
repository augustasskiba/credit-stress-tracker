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


STAGE_COLS = 3
PANEL_W_IN, PANEL_H_IN = 6.68 / 3, 1.0   # 3 panels across = 668 CSS px (the e-mail's content width)
STATUS_TEXT = {"amber": "#8a5a00", "red": "#b42318"}
FAINT = "#6b7280"


def _short(v: float) -> str:
    a = abs(v)
    return f"{v:,.0f}" if a >= 100 else f"{v:.0f}" if a >= 10 and float(v).is_integer() else f"{v:.1f}" if a >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")


def _draw_panel(ax, r: dict, rule: dict):
    from matplotlib.transforms import blended_transform_factory

    pts = r.get("chart") or []
    name = r["name"] if len(r["name"]) <= 27 else r["name"][:26] + "…"
    ax.set_title(name, loc="left", fontsize=7.4, color="#111827", pad=3)
    ax.text(1.0, 1.035, r.get("_value_text", ""), transform=ax.transAxes, ha="right", va="bottom",
            fontsize=7.4, color="#111827", fontweight="bold")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#d1d5db")
    ax.spines["bottom"].set_linewidth(0.6)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_facecolor("white")
    s = pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))
    lo, hi = float(s.min()), float(s.max())
    span = (hi - lo) or abs(hi) or 1.0
    zones = _zones(rule)
    for _, (op, v) in zones.items():
        if lo - 0.6 * span <= v <= hi + 0.6 * span:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.14 or 0.5
    y0, y1 = lo - pad, hi + pad
    lab = blended_transform_factory(ax.transAxes, ax.transData)
    for st in ("amber", "red"):
        if st in zones:
            op, v = zones[st]
            lo_b, hi_b = (v, y1) if op in ("gt", "ge") else (y0, v)
            ax.axhspan(lo_b, hi_b, color=STATUS[st], alpha=0.13 if st == "amber" else 0.17, lw=0)
            if y0 <= v <= y1:
                ax.axhline(v, color=STATUS[st], lw=0.7, alpha=0.9)
                ax.text(0.01, v, f"{st} {_short(v)}", transform=lab, fontsize=5.6, color=STATUS_TEXT[st],
                        ha="left", va="bottom" if op in ("gt", "ge") else "top")
    dense = len(s) > 20
    ax.plot(s.index, s.values, color=LINE, lw=1.15, marker=None if dense else "o", markersize=2.2,
            solid_joinstyle="round")
    ax.plot([s.index[-1]], [s.values[-1]], "o", color=STATUS.get(r["status"], LINE), markersize=5.2,
            markeredgecolor="white", markeredgewidth=1.0, zorder=5)
    ax.set_ylim(y0, y1)
    ax.set_xlim(s.index[0], s.index[-1] + (s.index[-1] - s.index[0]) * 0.04)
    fmt_d = "%b %Y" if (s.index[-1] - s.index[0]).days > 400 else "%d %b"
    ax.text(0.0, -0.05, s.index[0].strftime(fmt_d), transform=ax.transAxes, fontsize=5.6, color=FAINT, ha="left", va="top")
    ax.text(1.0, -0.05, s.index[-1].strftime(fmt_d), transform=ax.transAxes, fontsize=5.6, color=FAINT, ha="right", va="top")


def render_stage(results: list[dict], rules: dict[str, dict], path: Path) -> bool:
    """One small-multiples image per stage: a labelled panel per signal that has a series."""
    rows_ = [r for r in results if len(r.get("chart") or []) >= 2]
    if not rows_:
        return False
    n = len(rows_)
    nrows = (n + STAGE_COLS - 1) // STAGE_COLS
    fig, axes = plt.subplots(nrows, STAGE_COLS, figsize=(PANEL_W_IN * STAGE_COLS, PANEL_H_IN * nrows),
                             dpi=100 * SCALE, squeeze=False)
    for i, ax in enumerate(axes.flat):
        if i < n:
            _draw_panel(ax, rows_[i], rules.get(rows_[i]["id"], {}))
        else:
            ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=1 - 0.30 / nrows, bottom=0.12 / nrows, wspace=0.16, hspace=0.95)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100 * SCALE, facecolor="white")
    plt.close(fig)
    return True


def render_stages(results: list[dict], rules: dict[str, dict], out_dir: Path, value_fmt) -> list[dict]:
    """One PNG per stage (at most 4 images, inside Gmail's 10-attachment limit). Returns [{id, path, sha256}]."""
    out = []
    for st in (1, 2, 3, 4):
        rs = [dict(r, _value_text=value_fmt(r)) for r in results if r["stage"] == st]
        p = out_dir / f"stage{st}.png"
        if render_stage(rs, rules, p):
            out.append({"id": f"stage{st}", "path": str(p.resolve()),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return out


def render_all(results: list[dict], rules: dict[str, dict], out_dir: Path) -> list[dict]:
    """Render one PNG per signal with chart data. Returns [{id, path, sha256}] in table order."""
    out = []
    for r in results:
        p = out_dir / f"{r['id']}.png"
        if render(r.get("chart") or [], r["status"], rules.get(r["id"], {}), p):
            out.append({"id": r["id"], "path": str(p.resolve()),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return out
