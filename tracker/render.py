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
def _td(content: str, align="left", extra="") -> str:
    nowrap = "white-space:nowrap;" if align == "right" or extra == "nowrap" else ""
    return f'<td style="padding:6px 8px;border-bottom:1px solid #e5e7eb;text-align:{align};{nowrap}">{content}</td>'


def to_html(run: dict) -> str:
    e = html.escape
    comp = run["composite"]
    lc = LEVEL_COLORS.get(comp["level"], "#374151")
    parts = ['<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111827;max-width:760px;font-size:14px;line-height:1.45">']
    parts.append(f'<h2 style="margin:0 0 4px">Credit Stress Tracker</h2><div style="color:#6b7280;margin-bottom:12px">'
                 f'{e(run["mode"].title())} run · data as of {e(run["asof"])}</div>')
    parts.append(f'<div style="display:inline-block;background:{lc};color:#fff;padding:6px 12px;border-radius:6px;font-weight:600">'
                 f'Composite: {e(comp["name"])} · level {comp["level"]}/3</div>')
    parts.append('<ul style="margin:12px 0 16px;padding-left:20px">' +
                 "".join(f"<li>{e(x)}</li>" for x in summary_lines(run)) + "</ul>")

    if run["alerts"]:
        parts.append('<div style="border-left:4px solid #c53030;background:#fef2f2;padding:8px 12px;margin-bottom:16px">'
                     '<b>🔴 Alerts</b><ul style="margin:4px 0;padding-left:20px">' +
                     "".join(f"<li>{e(_alert_text(a))}</li>" for a in run["alerts"]) + "</ul></div>")
    stale = [r for r in run["results"] if r["status"] == "stale"]
    if stale:
        parts.append('<div style="border-left:4px solid #6b7280;background:#f3f4f6;padding:8px 12px;margin-bottom:16px">'
                     '<b>⚠ Data issues</b><ul style="margin:4px 0;padding-left:20px">' +
                     "".join(f"<li>{e(r['name'])}: {e(r['error'] or r['note'])}</li>" for r in stale) + "</ul></div>")

    for st, title in STAGES.items():
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        parts.append(f'<h3 style="margin:18px 0 6px;font-size:15px">{e(title)}</h3>')
        parts.append('<table style="border-collapse:collapse;width:100%;font-size:13px"><tr style="background:#f9fafb;color:#374151">'
                     + "".join(f'<th style="padding:6px 8px;text-align:{a};border-bottom:1px solid #d1d5db">{h}</th>'
                               for h, a in [("Signal", "left"), ("Value", "right"), ("1w Δ", "right"), ("3m Δ", "right"),
                                            ("Status", "left"), ("Trend", "left")]) + "</tr>")
        for r in rows:
            c = COLORS[r["status"]]
            note = f'<div style="color:#6b7280;font-size:11px">{e(r["note"])}</div>' if r["note"] and r["status"] != "stale" else ""
            asof = f'<div style="color:#9ca3af;font-size:11px;white-space:nowrap">as of {e(r["last_date"])}</div>' if r["last_date"] else ""
            parts.append("<tr>" + _td(e(r["name"]) + note) + _td(e(fmt(r["value"], r["unit"])) + asof, "right")
                         + _td(e(fmt(r["chg_1w"], r["unit"], True)), "right")
                         + _td(e(fmt(r["chg_3m"], r["unit"], True)), "right")
                         + _td(f'<span style="color:{c};font-weight:600">● {e(r["status"])}</span>', extra="nowrap")
                         + _td(f'<span style="font-family:Menlo,Consolas,monospace;color:{c};letter-spacing:-1px">{e(r["spark"])}</span>', extra="nowrap")
                         + "</tr>")
        parts.append("</table>")

    if run.get("fed_actions"):
        parts.append('<h3 style="margin:18px 0 6px;font-size:15px">Fed / official actions</h3><ul>' +
                     "".join(f"<li>{e(str(x['date']))}: {e(x['action'])}</li>" for x in run["fed_actions"]) + "</ul>")
    if run.get("upcoming"):
        parts.append('<h3 style="margin:18px 0 6px;font-size:15px">Upcoming (next 14 days)</h3><ul>' +
                     "".join(f"<li>{e(str(x['date']))}: {e(x['name'])}</li>" for x in run["upcoming"]) + "</ul>")
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        parts.append(f'<h3 style="margin:18px 0 6px;font-size:15px">EDGAR keyword scan (last {scan["lookback_days"]} days, filings mentioning)</h3>'
                     '<table style="border-collapse:collapse;font-size:13px"><tr>' +
                     "".join(f'<th style="padding:4px 8px;text-align:left;border-bottom:1px solid #d1d5db">{h}</th>' for h in ("Keyword", "Banks", "Insurers")) + "</tr>" +
                     "".join("<tr>" + _td(e(k)) + _td(str(v["banks"]["total"]), "right") + _td(str(v["insurers"]["total"]), "right") + "</tr>"
                             for k, v in scan["keywords"].items()) + "</table>")
    parts.append(f'<p style="color:#9ca3af;font-size:11px;margin-top:20px">{e(DISCLAIMER)}</p></div>')
    return "".join(parts)


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
