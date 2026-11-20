"""Render the weekly report / alert as e-mail-safe HTML (inline styles, no SVG/images) and Markdown."""
from __future__ import annotations

import html

STAGES = {
    1: "Stage 1 · Inside private credit",
    2: "Stage 2 · Credit markets",
    3: "Stage 3 · Transmission to banks & insurers",
    4: "Stage 4 · Funding stress",
}
COLORS = {"green": "#1a7f37", "amber": "#b7791f", "red": "#c53030", "stale": "#6b7280", "n/a": "#9ca3af"}
EMOJI = {"green": "🟢", "amber": "🟠", "red": "🔴", "stale": "⚪", "n/a": "▫️"}
LEVEL_COLORS = {0: "#1a7f37", 1: "#b7791f", 2: "#dd6b20", 3: "#c53030"}
DISCLAIMER = "Monitoring tool only, not investment advice or a timing signal. Thresholds are rules of thumb."


def fmt(v, unit: str, signed: bool = False) -> str:
    if v is None:
        return "–"
    dec = {"bp": 0, "%": 1, "x": 2, "$bn": 1, "days": 0, "qtrs": 0}.get(unit, 2)
    s = f"{v:+,.{dec}f}" if signed else f"{v:,.{dec}f}"
    suffix = {"bp": " bp", "%": "%", "x": "x", "$bn": " bn", "days": "", "qtrs": ""}.get(unit, "")
    if unit == "$bn":
        return ("$" + s if not signed else s[0] + "$" + s[1:]) + "bn"
    if signed and unit == "%":
        suffix = " pp"
    return s + suffix


def subject(run: dict) -> str:
    comp = run["composite"]
    n_red = sum(r["status"] == "red" for r in run["results"])
    n_amb = sum(r["status"] == "amber" for r in run["results"])
    n_stale = sum(r["status"] == "stale" for r in run["results"])
    pre = "🔴 ALERT · " if run["alerts"] else ""
    warn = " · ⚠ DATA ISSUE" if n_stale else ""
    kind = "Credit Stress" if run["mode"] == "weekly" else "Credit Stress daily check"
    return f"{pre}{kind} · {comp['name']} · {n_red} red, {n_amb} amber · {run['asof']}{warn}"


def _auto_summary(run: dict) -> list[str]:
    res = run["results"]
    reds = [r for r in res if r["status"] == "red"]
    ambers = [r for r in res if r["status"] == "amber"]
    comp = run["composite"]
    lines = [f"Composite reading: {comp['name']} (level {comp['level']} of 3)."]
    if reds:
        lines.append("Red: " + "; ".join(f"{r['name']} {fmt(r['value'], r['unit'])}" for r in reds) + ".")
    if ambers:
        lines.append("Amber: " + "; ".join(f"{r['name']} {fmt(r['value'], r['unit'])}" for r in ambers) + ".")
    if not reds and not ambers:
        lines.append("All scored signals are green.")
    return lines[:3]


def summary_lines(run: dict) -> list[str]:
    s = (run.get("summary") or "").strip()
    return [x.strip("-• ").strip() for x in s.splitlines() if x.strip()] if s else _auto_summary(run)


# ------------------------------------------------------------------ Markdown
def to_markdown(run: dict) -> str:
    comp = run["composite"]
    out = [f"# Credit Stress Tracker: {run['asof']} ({run['mode']})", "",
           f"**Composite: {comp['name']}** (level {comp['level']}/3)", ""]
    out += [f"- {x}" for x in summary_lines(run)] + [""]
    if run["alerts"]:
        out += ["## 🔴 Alerts", ""] + [f"- {_alert_text(a)}" for a in run["alerts"]] + [""]
    stale = [r for r in run["results"] if r["status"] == "stale"]
    if stale:
        out += ["## ⚠ Data issues", ""] + [f"- **{r['name']}**: {r['error'] or r['note']}" for r in stale] + [""]
    for st, title in STAGES.items():
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        out += [f"## {title}", "", "| Signal | Value | 1w Δ | 3m Δ | Status | Trend | As of |",
                "|---|---:|---:|---:|---|---|---|"]
        for r in rows:
            note = f" <br><sub>{r['note']}</sub>" if r["note"] and r["status"] != "stale" else ""
            out.append(f"| {r['name']}{note} | {fmt(r['value'], r['unit'])} | {fmt(r['chg_1w'], r['unit'], True)} | "
                       f"{fmt(r['chg_3m'], r['unit'], True)} | {EMOJI[r['status']]} {r['status']} | `{r['spark']}` | {r['last_date'] or '–'} |")
        out.append("")
    out += _context_md(run)
    out += ["---", f"_{DISCLAIMER}_", ""]
    return "\n".join(out)


def _alert_text(a: dict) -> str:
    if a["type"] == "new_red":
        return f"{a['name']} turned RED at {fmt(a['value'], a['unit'])} (was {a['previous']}, data {a['last_date']})"
    return f"Composite moved up: level {a['from']} → {a['to']} ({a['name']})"


def _context_md(run: dict) -> list[str]:
    out = []
    if run.get("fed_actions"):
        out += ["## Fed / official actions", ""] + [f"- {x['date']}: {x['action']}" for x in run["fed_actions"]] + [""]
    if run.get("upcoming"):
        out += ["## Upcoming (next 14 days)", ""] + [f"- {x['date']}: {x['name']}" for x in run["upcoming"]] + [""]
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        out += [f"## EDGAR keyword scan (last {scan['lookback_days']} days)", "",
                "| Keyword | Banks | Insurers |", "|---|---:|---:|"]
        for k, v in scan["keywords"].items():
            out.append(f"| {k} | {v['banks']['total']} | {v['insurers']['total']} |")
        out.append("")
    return out


# ------------------------------------------------------------------ HTML
# Compact e-mail HTML: one <style> block (Gmail supports embedded CSS) + short class names.
CSS = (
    "body,.w{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111827;font-size:14px;line-height:1.45}"
    ".w{max-width:760px}.m{color:#6b7280}.s{color:#9ca3af;font-size:11px}"
    "h3{margin:18px 0 6px;font-size:15px}"
    "table{border-collapse:collapse;width:100%;font-size:13px}"
    "th{padding:5px 7px;text-align:left;border-bottom:1px solid #d1d5db;background:#f9fafb;color:#374151}"
    "td{padding:5px 7px;border-bottom:1px solid #e5e7eb;vertical-align:top}"
    ".n{text-align:right;white-space:nowrap}.nw{white-space:nowrap}"
    ".sp{font-family:Menlo,Consolas,monospace;letter-spacing:-1px;white-space:nowrap}"
    ".green{color:#1a7f37}.amber{color:#b7791f}.red{color:#c53030}.stale{color:#6b7280}.na{color:#9ca3af}"
    ".box{padding:8px 12px;margin-bottom:14px;border-left:4px solid}.al{border-color:#c53030;background:#fef2f2}"
    ".di{border-color:#6b7280;background:#f3f4f6}"
    ".bd{display:inline-block;color:#fff;padding:6px 12px;border-radius:6px;font-weight:600}"
)


def _cls(status: str) -> str:
    return "na" if status == "n/a" else status


def _trend_cell(r: dict, c: str, img_src: dict) -> str:
    src = img_src.get(r["id"])
    if src:
        return f'<td class=nw><img src="{html.escape(src)}" width="180" height="40" alt="{html.escape(r["name"])} trend" style="display:block"></td>'
    return f'<td class="sp {c}">{html.escape(r["spark"])}</td>'


def to_html(run: dict, img_src: dict | None = None) -> str:
    """img_src: signal id -> image URL (cid:attN for e-mail, charts/x.png for the local file).
    Signals without an image fall back to the text sparkline."""
    img_src = img_src or {}
    e = html.escape
    comp = run["composite"]
    lc = LEVEL_COLORS.get(comp["level"], "#374151")
    p = [f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="w">',
         f'<h2 style="margin:0 0 4px">Credit Stress Tracker</h2>'
         f'<div class="m" style="margin-bottom:12px">{e(run["mode"].title())} run · data as of {e(run["asof"])}</div>',
         f'<div class="bd" style="background:{lc}">Composite: {e(comp["name"])} · level {comp["level"]}/3</div>',
         "<ul>" + "".join(f"<li>{e(x)}</li>" for x in summary_lines(run)) + "</ul>"]
    if run["alerts"]:
        p.append('<div class="box al"><b>🔴 Alerts</b><ul>' +
                 "".join(f"<li>{e(_alert_text(a))}</li>" for a in run["alerts"]) + "</ul></div>")
    stale = [r for r in run["results"] if r["status"] == "stale"]
    if stale:
        p.append('<div class="box di"><b>⚠ Data issues</b><ul>' +
                 "".join(f"<li>{e(r['name'])}: {e(r['error'] or r['note'])}</li>" for r in stale) + "</ul></div>")
    for st, title in STAGES.items():
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        p.append(f"<h3>{e(title)}</h3><table><tr><th>Signal</th><th class=n>Value</th><th class=n>1w Δ</th>"
                 "<th class=n>3m Δ</th><th>Status</th><th>Trend (6m)</th></tr>")
        for r in rows:
            c = _cls(r["status"])
            note = f'<div class="s">{e(r["note"])}</div>' if r["note"] and r["status"] != "stale" else ""
            asof = f'<div class="s">{e(r["last_date"])}</div>' if r["last_date"] else ""
            p.append(f'<tr><td>{e(r["name"])}{note}</td><td class=n>{e(fmt(r["value"], r["unit"]))}{asof}</td>'
                     f'<td class=n>{e(fmt(r["chg_1w"], r["unit"], True))}</td><td class=n>{e(fmt(r["chg_3m"], r["unit"], True))}</td>'
                     f'<td class="nw {c}"><b>● {e(r["status"])}</b></td>{_trend_cell(r, c, img_src)}</tr>')
        p.append("</table>")
    if run.get("fed_actions"):
        p.append("<h3>Fed / official actions</h3><ul>" +
                 "".join(f"<li>{e(str(x['date']))}: {e(x['action'])}</li>" for x in run["fed_actions"]) + "</ul>")
    if run.get("upcoming"):
        p.append("<h3>Upcoming (next 14 days)</h3><ul>" +
                 "".join(f"<li>{e(str(x['date']))}: {e(x['name'])}</li>" for x in run["upcoming"]) + "</ul>")
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        p.append(f'<h3>EDGAR keyword scan (filings in last {scan["lookback_days"]} days)</h3>'
                 '<table style="width:auto"><tr><th>Keyword</th><th class=n>Banks</th><th class=n>Insurers</th></tr>' +
                 "".join(f'<tr><td>{e(k)}</td><td class=n>{v["banks"]["total"]}</td><td class=n>{v["insurers"]["total"]}</td></tr>'
                         for k, v in scan["keywords"].items()) + "</table>")
    p.append(f'<p class="s" style="margin-top:20px">{e(DISCLAIMER)}</p></div></body></html>')
    return "".join(p)


def to_text(run: dict) -> str:
    """Plain-text alternative for the e-mail."""
    comp = run["composite"]
    lines = [f"Credit Stress Tracker · {run['asof']} · Composite: {comp['name']} (level {comp['level']}/3)", ""]
    lines += summary_lines(run) + [""]
    for a in run["alerts"]:
        lines.append("ALERT: " + _alert_text(a))
    for st, title in STAGES.items():
        lines.append("")
        lines.append(title)
        for r in [r for r in run["results"] if r["stage"] == st]:
            lines.append(f"  {r['status'].upper():6} {r['name']}: {fmt(r['value'], r['unit'])}  {r['spark']}")
    lines += ["", DISCLAIMER]
    return "\n".join(lines)
