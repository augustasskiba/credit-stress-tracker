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
    return re.sub(rf"(?:{_SEC_URL.pattern}[\s,;]*)+", "[SEC filing links in the full report] ", text).strip()


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
    stale = [r for r in run["results"] if r["status"] == "stale" or r.get("warning")]
    if stale:
        out += ["## ⚠ Data issues", ""] + [f"- **{r['name']}**: {r.get('warning') or r['error'] or r['note']}" for r in stale] + [""]
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
        prev = scan.get("prev_asof")
        cmp = f"vs previous scan on {prev}" if prev else "first scan on record"
        out += [f"## SEC filing keyword scan (last {scan['lookback_days']} days, {cmp})", "",
                "| Keyword | Banks | vs last | Insurers | vs last | New filings |", "|---|---:|---:|---:|---:|---:|"]

        def d(v):
            x = v.get("delta")
            return "–" if x is None else ("±0" if x == 0 else f"{x:+d}")
        new_all = []
        for k, v in scan["keywords"].items():
            b, i = v.get("banks", {}), v.get("insurers", {})
            nn = b.get("new_items", []) + i.get("new_items", [])
            new_all += [(k, x) for x in nn]
            out.append(f"| {k} | {b.get('total', 0)} | {d(b)} | {i.get('total', 0)} | {d(i)} | {len(nn) if prev else '–'} |")
        out.append("")
        if new_all:
            out += ["**New filings since the last scan**", ""]
            out += [f"- [{x.get('company')} · {x.get('form')} · {x.get('filed')}]({x.get('url')}) ({k})" for k, x in new_all[:20]]
            out.append("")
    return out


# ------------------------------------------------------------------ HTML
# E-mail HTML. Every element carries inline styles: Gmail drops <style> blocks in many views.
# Layout is a single centred 720px column; nothing inside may force it wider (long URLs in notes
# become short wrapped links), otherwise mail clients shrink the whole message to fit.
# Status colours always come with a text label (pill), never colour alone.
FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
INK, MUTED, FAINT, RULE, SURFACE = "#111827", "#4b5563", "#6b7280", "#e5e7eb", "#f8f9fb"
PILL = {"green": ("#e7f6ec", "#16733a", "Green"), "amber": ("#fff3d6", "#8a5a00", "Amber"),
        "red": ("#fde8e8", "#b42318", "Red"), "stale": ("#eef0f3", "#4b5563", "Stale"),
        "n/a": ("#f3f4f6", "#6b7280", "n/a")}
WORSE, BETTER = "#b42318", "#16733a"
STAGE_SHORT = {1: "Private credit", 2: "Credit markets", 3: "Banks & insurers", 4: "Funding markets"}
TH = "padding:7px 6px;border-bottom:1px solid #d1d5db;color:#6b7280;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;text-align:left"
TD = f"padding:8px 6px;border-bottom:1px solid {RULE};vertical-align:top;font-size:13px"
NUM = "text-align:right;white-space:nowrap"
NOTE = f"color:{FAINT};font-size:11px;line-height:1.45;margin-top:3px;word-break:break-word;overflow-wrap:anywhere"
TABLE_ATTR = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
TABLE = TABLE_ATTR + ' style="border-collapse:collapse;width:100%;table-layout:fixed"'
_URL = re.compile(r"https?://[^\s<>\"')]+")
_DEC = {"bp": 0, "%": 1, "x": 2, "$bn": 1, "days": 0, "qtrs": 0}


def _pill(status: str, small: bool = False) -> str:
    bg, fg, label = PILL.get(status, PILL["n/a"])
    size = "11px"
    return (f'<span style="display:inline-block;background:{bg};color:{fg};border-radius:999px;'
            f'padding:2px 8px;font-size:{size};font-weight:600;white-space:nowrap">{label}</span>')


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


def _delta(r: dict, key: str) -> str:
    v = r.get(key)
    if v is None:
        return f'<span style="color:{FAINT}">–</span>'
    txt = html.escape(fmt(v, r["unit"], True))
    if round(v, _DEC.get(r["unit"], 2)) == 0 or not r.get("direction"):
        return f'<span style="color:{FAINT}">{txt}</span>'
    worse = (v > 0) == (r["direction"] > 0)
    arrow = "▲" if v > 0 else "▼"
    return (f'<span style="color:{WORSE if worse else BETTER}"><span style="font-size:9px">{arrow}</span>&nbsp;{txt}</span>')


def _counts(rows: list[dict]) -> dict:
    return {s: sum(r["status"] == s for r in rows) for s in ("red", "amber", "green", "stale", "n/a")}


def _counts_line(c: dict) -> str:
    parts = []
    for s in ("red", "amber", "green"):
        if c[s]:
            _, fg, label = PILL[s]
            parts.append(f'<span style="color:{fg};font-weight:600">{c[s]}&nbsp;{label.lower()}</span>')
    other = c["stale"] + c["n/a"]
    if other:
        parts.append(f'<span style="color:{FAINT}">{other}&nbsp;n/a</span>')
    return " · ".join(parts)


def _worst(c: dict) -> str:
    return "red" if c["red"] else "amber" if c["amber"] else "green" if c["green"] else "n/a"


def _trend_cell(r: dict, img_src: dict) -> str:
    return (f'<td style="{TD};font-family:Menlo,Consolas,monospace;letter-spacing:-1px;white-space:nowrap;'
            f'color:{PILL.get(r["status"], PILL["n/a"])[1]}">{html.escape(r["spark"])}</td>')


def _ladder(run: dict) -> str:
    comp = run["composite"]
    levels = run.get("composite_levels") or [{"level": comp["level"], "name": comp["name"]}]
    cells = []
    for lv in levels:
        on = lv["level"] == comp["level"]
        col = LEVEL_COLORS.get(lv["level"], "#374151")
        style = (f"background:{col};color:#ffffff;font-weight:700" if on
                 else f"background:#f1f2f4;color:{FAINT if lv['level'] > comp['level'] else MUTED}")
        mark = "● " if on else ""
        cells.append(f'<td style="padding:9px 6px;text-align:center;font-size:12px;line-height:1.3;{style};'
                     f'border-left:2px solid #ffffff">{mark}{html.escape(lv["name"])}'
                     f'<div style="font-size:10px;opacity:.85;margin-top:1px">Level {lv["level"]}</div></td>')
    return (f'<table {TABLE_ATTR} style="border-collapse:collapse;width:100%;table-layout:fixed;border-radius:8px;overflow:hidden">'
            f'<tr>{"".join(cells)}</tr></table>')


def _stage_tiles(run: dict) -> str:
    tiles = []
    for st in STAGES:
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        c = _counts(rows)
        top = PILL[_worst(c)][1]
        tiles.append(f'<td style="padding:0 3px;vertical-align:top"><div style="border:1px solid {RULE};border-top:3px solid {top};'
                     f'border-radius:6px;padding:9px 10px;background:#ffffff">'
                     f'<div style="font-size:10px;color:{FAINT};text-transform:uppercase;letter-spacing:.05em">Stage {st}</div>'
                     f'<div style="font-size:13px;font-weight:600;margin:1px 0 4px">{STAGE_SHORT[st]}</div>'
                     f'<div style="font-size:12px;line-height:1.5">{_counts_line(c)}</div></div></td>')
    return (f'<table {TABLE_ATTR} style="border-collapse:separate;width:100%;table-layout:fixed">'
            f'<tr>{"".join(tiles)}</tr></table>')


def _edgar_html(scan: dict, email: bool) -> str:
    kws = scan.get("keywords") or {}
    if not kws:
        return ""
    prev = scan.get("prev_asof")

    def cell(v: dict) -> str:
        d = v.get("delta")
        if prev is None or d is None:
            dtxt = f'<span style="color:{FAINT}">new</span>' if prev is None else f'<span style="color:{FAINT}">–</span>'
        elif d == 0:
            dtxt = f'<span style="color:{FAINT}">±0</span>'
        else:
            dtxt = f'<span style="color:{WORSE if d > 0 else BETTER}">{"▲" if d > 0 else "▼"}&nbsp;{abs(d)}</span>'
        return (f'<td style="{TD};{NUM}"><b>{v.get("total", 0)}</b></td>'
                f'<td style="{TD};{NUM};font-size:12px">{dtxt}</td>')

    head = (f'<tr><th style="{TH}">Keyword</th><th style="{TH};{NUM}">Banks</th><th style="{TH};{NUM}">vs last</th>'
            f'<th style="{TH};{NUM}">Insurers</th><th style="{TH};{NUM}">vs last</th><th style="{TH};{NUM}">New</th></tr>')
    body = []
    new_all = []
    for kw, g in kws.items():
        b, i = g.get("banks", {}), g.get("insurers", {})
        n_new = len(b.get("new_items", [])) + len(i.get("new_items", []))
        new_all += [(kw, x) for x in b.get("new_items", []) + i.get("new_items", [])]
        ntxt = (f'<b style="color:{WORSE}">{n_new}</b>' if n_new else f'<span style="color:{FAINT}">0</span>') if prev else f'<span style="color:{FAINT}">–</span>'
        body.append(f'<tr><td style="{TD}">{html.escape(kw)}</td>{cell(b)}{cell(i)}<td style="{TD};{NUM}">{ntxt}</td></tr>')
    cmp = (f'Compared with the previous scan on <b>{html.escape(prev)}</b>.' if prev
           else 'First scan on record: changes will show from the next weekly run.')
    out = [f'<div style="color:{MUTED};font-size:12px;margin:0 0 6px">Filings that mention each keyword in the last '
           f'{scan.get("lookback_days", 30)} days (10-Q, 10-K, 8-K). {cmp}</div>',
           f'<table {TABLE}><colgroup><col style="width:31%"><col style="width:13%"><col style="width:13%"><col style="width:14%">'
           f'<col style="width:13%"><col style="width:16%"></colgroup>{head}{"".join(body)}</table>']
    if new_all:
        order = {k: n for n, k in enumerate(["NAV loan", "fund finance", "nondepository financial", "reserve build", "charge-off", "fraud"])}
        new_all.sort(key=lambda kx: (order.get(kx[0], 9), kx[1].get("filed") or ""), reverse=False)
        items = []
        for kw, x in new_all[:8]:
            label = f'{html.escape(x.get("company") or "?")} · {html.escape(x.get("form") or "")} · {html.escape(x.get("filed") or "")}'
            if not email and x.get("url"):
                label = f'<a href="{html.escape(x["url"])}" style="color:{INK}">{label}</a>'
            items.append(f'<li style="margin-bottom:3px">{label} <span style="color:{FAINT}">({html.escape(kw)})</span></li>')
        more = f'<li style="color:{FAINT}">and {len(new_all) - 8} more</li>' if len(new_all) > 8 else ""
        where = " Filing links are in the full report." if email else ""
        out.append(f'<div style="font-size:12px;font-weight:600;margin:12px 0 4px">New filings since the last scan</div>'
                   f'<ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.45">{"".join(items)}{more}</ul>'
                   f'<div style="color:{FAINT};font-size:11px;margin-top:4px">"New" = not among the top results of any earlier scan.{where}</div>')
    return "".join(out)


def _section(title: str, right: str = "", badge: str = "") -> str:
    b = (f'<span style="display:inline-block;width:22px;height:22px;line-height:22px;border-radius:11px;background:{INK};'
         f'color:#ffffff;text-align:center;font-size:12px;font-weight:700;margin-right:8px">{badge}</span>') if badge else ""
    return (f'<table {TABLE_ATTR} style="border-collapse:collapse;width:100%;margin:28px 0 8px"><tr>'
            f'<td style="font-size:17px;font-weight:700;color:{INK};vertical-align:middle">{b}{html.escape(title)}</td>'
            f'<td style="text-align:right;font-size:12px;vertical-align:middle;width:45%">{right}</td></tr></table>')


def to_html(run: dict, img_src: dict | None = None, email: bool = False) -> str:
    """img_src: 'stage1'..'stage4' -> image URL (cid:attN in e-mail, charts/x.png locally).
    email=True leaves SEC filing links out (the owner's choice; they stay in the repo report)."""
    img_src = img_src or {}
    e = html.escape
    comp = run["composite"]
    p = ['<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
         f'<body style="margin:0;padding:0;background:#eef0f3;{FONT}">'
         '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eef0f3"><tr><td align="center" style="padding:16px 6px">'
         '<table role="presentation" width="720" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:720px;table-layout:fixed;background:#ffffff;border-radius:10px">'
         f'<tr><td style="{FONT};color:{INK};font-size:14px;line-height:1.5;text-align:left;padding:22px 18px 16px">']

    # Header
    kind = "Weekly report" if run["mode"] == "weekly" else "Daily red-alert check"
    p.append(f'<div style="font-size:11px;color:{FAINT};text-transform:uppercase;letter-spacing:.08em">{kind} · data as of {e(run["asof"])}</div>'
             f'<div style="font-size:24px;font-weight:800;margin:2px 0 14px;letter-spacing:-.01em">Credit Stress Tracker</div>')
    p.append(_ladder(run))
    p.append(f'<div style="font-size:12px;color:{MUTED};margin:6px 0 16px">Composite reading: <b style="color:{INK}">{e(comp["name"])}</b>. '
             'Levels rise when stress spreads from private credit to banks (level 2) and funding markets (level 3).</div>')

    # Summary
    p.append(f'<div style="background:{SURFACE};border:1px solid {RULE};border-radius:8px;padding:12px 16px 4px;margin-bottom:16px">'
             f'<div style="font-size:11px;color:{FAINT};text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">This week</div>'
             '<ul style="margin:0 0 8px;padding-left:18px">' +
             "".join(f'<li style="margin-bottom:6px">{e(x)}</li>' for x in summary_lines(run)) + "</ul></div>")

    if run["alerts"]:
        p.append(f'<div style="border:1px solid #f5c2c0;border-left:4px solid {WORSE};background:#fff5f5;border-radius:6px;padding:10px 14px;margin-bottom:16px">'
                 f'<div style="font-weight:700;color:{WORSE};margin-bottom:4px">🔴 New red signals</div><ul style="margin:0;padding-left:18px">' +
                 "".join(f'<li style="margin-bottom:2px">{e(_alert_text(a))}</li>' for a in run["alerts"]) + "</ul></div>")
    stale = [r for r in run["results"] if r["status"] == "stale" or r.get("warning")]
    if stale:
        p.append(f'<div style="border:1px solid {RULE};border-left:4px solid {FAINT};background:{SURFACE};border-radius:6px;padding:10px 14px;margin-bottom:16px">'
                 '<div style="font-weight:700;margin-bottom:4px">⚠ Data issues</div><ul style="margin:0;padding-left:18px">' +
                 "".join(f"<li>{e(r['name'])}: {e(r.get('warning') or r['error'] or r['note'])}</li>" for r in stale) + "</ul></div>")

    p.append(_stage_tiles(run))

    # Stages
    for st, title in STAGES.items():
        rows = [r for r in run["results"] if r["stage"] == st]
        if not rows:
            continue
        stage_img = img_src.get(f"stage{st}")
        p.append(_section(title.split(" · ", 1)[1], _counts_line(_counts(rows)), str(st)))
        cols = ('<col style="width:44%"><col style="width:18%"><col style="width:23%"><col style="width:15%">' if stage_img
                else '<col style="width:34%"><col style="width:16%"><col style="width:20%"><col style="width:13%"><col style="width:17%">')
        p.append(f'<table {TABLE}><colgroup>{cols}</colgroup><tr><th style="{TH}">Signal</th><th style="{TH};{NUM}">Value</th>'
                 f'<th style="{TH};{NUM}">Change</th><th style="{TH}">Status</th>'
                 + ("" if stage_img else f'<th style="{TH}">Trend</th>') + "</tr>")
        for r in rows:
            note = f'<div style="{NOTE}">{_note_html(r["note"])}</div>' if r["note"] and r["status"] != "stale" else ""
            asof = f'<div style="color:{FAINT};font-size:10px;font-weight:400">{e(r["last_date"])}</div>' if r["last_date"] else ""
            p.append(f'<tr><td style="{TD};word-break:break-word">{e(r["name"])}{note}</td>'
                     f'<td style="{TD};{NUM};font-weight:600">{e(fmt(r["value"], r["unit"]))}{asof}</td>'
                     f'<td style="{TD};{NUM};font-size:12px;line-height:1.55">{_delta(r, "chg_1w")}<br>{_delta(r, "chg_3m")}</td>'
                     f'<td style="{TD}">{_pill(r["status"])}</td>' + ("" if stage_img else _trend_cell(r, img_src)) + "</tr>")
        p.append("</table>")
        if stage_img:
            p.append(f'<img src="{e(stage_img)}" width="668" alt="{e(title)}: trend charts" '
                     f'style="display:block;width:100%;max-width:668px;height:auto;border:0;margin-top:12px">')
    p.append(f'<div style="color:{FAINT};font-size:11px;margin-top:10px">Change column: 1-week change on top, 3-month change below. '
             f'Arrows: <span style="color:{WORSE}">▲▼ toward stress</span> · '
             f'<span style="color:{BETTER}">▲▼ away from stress</span>. Charts show 6 months of daily data (last 12 readings for monthly/quarterly '
             'series); shaded bands are the amber and red zones, the dot is the latest value.</div>')

    # Context
    if run.get("fed_actions"):
        p.append(_section("Fed and official actions") + '<ul style="margin:0;padding-left:18px">' +
                 "".join(f"<li>{e(str(x['date']))}: {e(x['action'])}</li>" for x in run["fed_actions"]) + "</ul>")
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        p.append(_section("SEC filing keyword scan") + _edgar_html(scan, email))
    if run.get("upcoming"):
        p.append(_section("Coming up (next 14 days)") + f'<table {TABLE}>' +
                 "".join(f'<tr><td style="{TD};width:26%;white-space:nowrap;color:{MUTED}">{e(str(x["date"]))}</td>'
                         f'<td style="{TD}">{e(x["name"])}</td></tr>' for x in run["upcoming"]) + "</table>")

    # Footer
    link = ""
    if run.get("report_url"):
        link = (f'<a href="{e(run["report_url"])}" style="display:inline-block;background:{INK};color:#ffffff;text-decoration:none;'
                f'font-size:13px;font-weight:600;padding:9px 16px;border-radius:6px;margin:26px 0 6px">Full report with sources on GitHub →</a>')
    p.append(f'{link}<div style="color:{FAINT};font-size:11px;margin-top:14px;border-top:1px solid {RULE};padding-top:10px">'
             f'{e(DISCLAIMER)} Generated {e(run.get("generated_utc", ""))}.</div>'
             "</td></tr></table></td></tr></table></body></html>")
    return "".join(p)


def to_text(run: dict) -> str:
    """Plain-text alternative for the e-mail."""
    comp = run["composite"]
    lines = [f"Credit Stress Tracker · {run['asof']} · Composite: {comp['name']} (level {comp['level']}/3)", ""]
    lines += summary_lines(run) + [""]
    for a in run["alerts"]:
        lines.append("ALERT: " + _alert_text(a))
    for r in run["results"]:
        if r.get("warning"):
            lines.append(f"DATA: {r['name']}: {r['warning']}")
    for st, title in STAGES.items():
        lines.append("")
        lines.append(title)
        for r in [r for r in run["results"] if r["stage"] == st]:
            lines.append(f"  {r['status'].upper():6} {r['name']}: {fmt(r['value'], r['unit'])}  {r['spark']}")
    scan = run.get("edgar_scan") or {}
    if scan.get("keywords"):
        prev = scan.get("prev_asof")
        lines += ["", f"SEC filing keyword scan ({'vs ' + prev if prev else 'first scan on record'})"]
        for k, v in scan["keywords"].items():
            b, i = v.get("banks", {}), v.get("insurers", {})
            dd = lambda g: "" if g.get("delta") is None else f" ({g['delta']:+d})"
            nn = len(b.get("new_items", [])) + len(i.get("new_items", []))
            lines.append(f"  {k}: banks {b.get('total', 0)}{dd(b)}, insurers {i.get('total', 0)}{dd(i)}, new filings {nn}")
    if run.get("report_url"):
        lines += ["", f"Full report: {run['report_url']}"]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)
