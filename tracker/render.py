"""Render the weekly report / alert as e-mail-safe HTML (inline styles, no SVG/images) and Markdown."""
from __future__ import annotations

import html
import re

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


_SEC_URL = re.compile(r"https?://(?:www\.|efts\.|data\.)?sec\.gov/[^\s<>\"')]*")


def email_safe(text: str) -> str:
    """Replace SEC links in e-mail bodies with a pointer to the repo report (owner's choice, 2026-11-20).
    The session's privacy guard refuses Gmail sends that put the owner's address next to sec.gov
    links; the full links stay in reports/<date>.md and config/manual_inputs.yaml."""
    return _SEC_URL.sub("[SEC filing: link in repo report]", text)


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
# E-mail HTML. Every element carries inline styles: Gmail drops <style> blocks in many views.
# Layout is a single centred 720px column; nothing inside may force it wider (long URLs in notes
# become short wrapped links), otherwise mail clients shrink the whole message to fit.
FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
INK, MUTED, FAINT, RULE = "#111827", "#4b5563", "#6b7280", "#e5e7eb"
TXT = {"green": "#1a7f37", "amber": "#9a6200", "red": "#c53030", "stale": "#6b7280", "n/a": "#6b7280"}
# Cell styles stay short (font family/colour inherit from the wrapper cell) to keep the e-mail small.
TH = "padding:6px 8px;border-bottom:1px solid #d1d5db;background:#f9fafb;color:#374151;font-size:12px;text-align:left"
TD = f"padding:7px 8px;border-bottom:1px solid {RULE};vertical-align:top;font-size:13px"
NUM = "text-align:right;white-space:nowrap"
NOTE = f"color:{FAINT};font-size:11px;line-height:1.4;margin-top:2px;word-break:break-word;overflow-wrap:anywhere"
H3 = f"margin:22px 0 6px;font-size:16px;color:{INK};{FONT}"
_URL = re.compile(r"https?://[^\s<>\"')]+")


def _note_html(text: str) -> str:
    """Escape a note and turn each URL into a short 'domain' link that can wrap."""
    out, last = [], 0
    for m in _URL.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        url = m.group(0).rstrip(".,;")
        dom = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        out.append(f'<a href="{html.escape(url)}" style="color:{MUTED}">{html.escape(dom)}</a>')
        last = m.start() + len(m.group(0))
    out.append(html.escape(text[last:]))
    return "".join(out)


def _trend_cell(r: dict, img_src: dict) -> str:
    src = img_src.get(r["id"])
    if src:
        return f'<td style="{TD}"><img src="{html.escape(src)}" width="180" height="40" alt="" style="display:block"></td>'
    return (f'<td style="{TD};font-family:Menlo,Consolas,monospace;letter-spacing:-1px;white-space:nowrap;'
            f'color:{TXT.get(r["status"], MUTED)}">{html.escape(r["spark"])}</td>')


def to_html(run: dict, img_src: dict | None = None) -> str:
    """img_src: 'stage1'..'stage4' (or signal id) -> image URL (cid:attN in e-mail, charts/x.png locally).
    Without an image a stage falls back to text sparklines."""
    img_src = img_src or {}
    e = html.escape
    comp = run["composite"]
    lc = LEVEL_COLORS.get(comp["level"], "#374151")
    p = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
         f'<body style="margin:0;padding:0;background:#ffffff;{FONT}">'
         '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="padding:16px 12px">'
         '<table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:720px;table-layout:fixed">'
         f'<tr><td style="{FONT};color:{INK};font-size:14px;line-height:1.5;text-align:left">']
    p.append(f'<div style="font-size:22px;font-weight:700;margin:0 0 2px">Credit Stress Tracker</div>'
             f'<div style="color:{FAINT};font-size:13px;margin-bottom:12px">{e(run["mode"].title())} run · data as of {e(run["asof"])}</div>'
             f'<div style="display:inline-block;background:{lc};color:#ffffff;padding:7px 14px;border-radius:6px;font-weight:600;font-size:14px">'
             f'Composite: {e(comp["name"])} · level {comp["level"]}/3</div>')
    p.append('<ul style="margin:14px 0 18px;padding-left:20px">' +
             "".join(f'<li style="margin-bottom:6px">{e(x)}</li>' for x in summary_lines(run)) + "</ul>")
    if run["alerts"]:
        p.append('<div style="border-left:4px solid #c53030;background:#fef2f2;padding:10px 14px;margin-bottom:16px">'
                 '<div style="font-weight:700;margin-bottom:4px">🔴 Alerts</div><ul style="margin:0;padding-left:20px">' +
                 "".join(f"<li>{e(_alert_text(a))}</li>" for a in run["alerts"]) + "</ul></div>")
    stale = [r for r in run["results"] if r["status"] == "stale"]
    if stale:
        p.append('<div style="border-left:4px solid #6b7280;background:#f3f4f6;padding:10px 14px;margin-bottom:16px">'
                 '<div style="font-weight:700;margin-bottom:4px">⚠ Data issues</div><ul style="margin:0;padding-left:20px">' +
                 "".join(f"<li>{e(r['name'])}: {e(r['error'] or r['note'])}</li>" for r in stale) + "</ul></div>")

    for st, title in STAGES.items():
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        stage_img = img_src.get(f"stage{st}")
        cols = ('<col><col style="width:84px"><col style="width:70px"><col style="width:70px"><col style="width:74px">'
                + ("" if stage_img else '<col style="width:120px">'))
        p.append(f'<div style="{H3}">{e(title)}</div>'
                 f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:100%;table-layout:fixed">'
                 f'<colgroup>{cols}</colgroup><tr><th style="{TH}">Signal</th><th style="{TH};{NUM}">Value</th>'
                 f'<th style="{TH};{NUM}">1w Δ</th><th style="{TH};{NUM}">3m Δ</th><th style="{TH}">Status</th>'
                 + ("" if stage_img else f'<th style="{TH}">Trend</th>') + "</tr>")
        for r in rows:
            c = TXT.get(r["status"], MUTED)
            note = (f'<div style="{NOTE}">{_note_html(r["note"])}</div>'
                    if r["note"] and r["status"] != "stale" else "")
            asof = f'<div style="color:{FAINT};font-size:11px">{e(r["last_date"])}</div>' if r["last_date"] else ""
            p.append(f'<tr><td style="{TD};word-break:break-word">{e(r["name"])}{note}</td>'
                     f'<td style="{TD};{NUM}">{e(fmt(r["value"], r["unit"]))}{asof}</td>'
                     f'<td style="{TD};{NUM}">{e(fmt(r["chg_1w"], r["unit"], True))}</td>'
                     f'<td style="{TD};{NUM}">{e(fmt(r["chg_3m"], r["unit"], True))}</td>'
                     f'<td style="{TD};white-space:nowrap;color:{c};font-weight:600">● {e(r["status"])}</td>'
                     + ("" if stage_img else _trend_cell(r, img_src)) + "</tr>")
        p.append("</table>")
        if stage_img:
            p.append(f'<div style="color:{FAINT};font-size:11px;margin:10px 0 4px">Trends over the last 6 months '
                     '(last 12 readings for monthly/quarterly series). Shaded bands are the amber/red zones; the dot is the latest value.</div>'
                     f'<img src="{e(stage_img)}" width="720" alt="{e(title)} trend charts" '
                     'style="display:block;width:100%;max-width:720px;height:auto;border:0">')

    if run.get("fed_actions"):
        p.append(f'<div style="{H3}">Fed / official actions</div><ul style="padding-left:20px">' +
                 "".join(f"<li>{e(str(x['date']))}: {e(x['action'])}</li>" for x in run["fed_actions"]) + "</ul>")
    if run.get("upcoming"):
        p.append(f'<div style="{H3}">Upcoming (next 14 days)</div><ul style="padding-left:20px;margin-top:4px">' +
                 "".join(f"<li>{e(str(x['date']))}: {e(x['name'])}</li>" for x in run["upcoming"]) + "</ul>")
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        p.append(f'<div style="{H3}">EDGAR keyword scan <span style="color:{FAINT};font-weight:400;font-size:13px">'
                 f'(filings in the last {scan["lookback_days"]} days)</span></div>'
                 f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse">'
                 f'<tr><th style="{TH}">Keyword</th><th style="{TH};{NUM}">Banks</th><th style="{TH};{NUM}">Insurers</th></tr>' +
                 "".join(f'<tr><td style="{TD}">{e(k)}</td><td style="{TD};{NUM}">{v["banks"]["total"]}</td>'
                         f'<td style="{TD};{NUM}">{v["insurers"]["total"]}</td></tr>' for k, v in scan["keywords"].items())
                 + "</table>")
    p.append(f'<p style="color:{FAINT};font-size:11px;margin-top:24px">{e(DISCLAIMER)}</p>'
             "</td></tr></table></td></tr></table></body></html>")
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
