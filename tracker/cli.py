"""Command line: verify | run | finalize | replay.

Typical scheduled flow (see RUNBOOK.md):
    python -m tracker run --mode weekly      # fetch + score -> out/run.json (no history written)
    ... Claude reviews news / EDGAR, updates config/manual_inputs.yaml, writes out/summary.md ...
    python -m tracker finalize               # re-score with manual inputs, alerts, render, append history
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from . import composite as comp_mod
from . import history, render
from .data import DataStore
from .signals import score_all
from .sources import edgar

ROOT = Path(__file__).resolve().parent.parent
CFG, OUT, DATA, REPORTS = ROOT / "config", ROOT / "out", ROOT / "data", ROOT / "reports"


def load_yaml(name: str) -> dict:
    with open(CFG / name) as f:
        return yaml.safe_load(f) or {}


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


# ---------------------------------------------------------------- shared pieces
def upcoming_events(asof: dt.date, days: int = 14) -> list[dict]:
    ev = load_yaml("calendar.yaml").get("events", [])
    out = []
    for x in ev:
        d = pd.Timestamp(x["date"]).date()
        if asof - dt.timedelta(days=3) <= d <= asof + dt.timedelta(days=days):
            out.append({"date": d.isoformat(), "name": x["name"]})
    return sorted(out, key=lambda x: x["date"])


def edgar_scan(settings: dict, asof: dt.date) -> dict:
    e = settings.get("edgar", {})
    lb = int(e.get("lookback_days", 30))
    start = asof - dt.timedelta(days=lb)
    groups = {}
    for g in ("banks", "insurers"):
        ciks = []
        for t in e.get(g, []):
            try:
                ciks.append(edgar.cik(t))
            except Exception:  # noqa: BLE001
                pass
        groups[g] = ciks
    out = {"lookback_days": lb, "keywords": {}, "errors": []}
    for kw in e.get("keywords", []):
        out["keywords"][kw] = {}
        for g, ciks in groups.items():
            try:
                out["keywords"][kw][g] = edgar.full_text_hits(kw, ciks, start, asof, e.get("forms", ["10-Q", "10-K", "8-K"]))
            except Exception as exc:  # noqa: BLE001
                out["keywords"][kw][g] = {"total": 0, "items": []}
                out["errors"].append(f"{kw}/{g}: {exc}")
    return out


def build_run(ds: DataStore, mode: str, asof: dt.date, extra: dict | None = None) -> dict:
    sig_cfg = load_yaml("signals.yaml")["signals"]
    if mode == "daily":
        sig_cfg = [s for s in sig_cfg if s["stage"] in (2, 4)]
    manual = load_yaml("manual_inputs.yaml")
    settings = load_yaml("settings.yaml")
    results = score_all(sig_cfg, ds, manual, asof, int(settings.get("sparkline_points", 13)))
    comp = comp_mod.composite(results, load_yaml("composite.yaml"))
    # Signal statuses: compare with the latest run of any mode. Composite: same mode only,
    # because the daily run sees only Stages 2 and 4 and would otherwise read lower.
    prev_status, prev_level = history.previous_state(DATA, mode, exclude_prefix=f"{asof.isoformat()}-{mode}-")
    alerts = history.compute_alerts(results, comp, prev_status, prev_level)
    run = {
        "mode": mode,
        "asof": asof.isoformat(),
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "composite": comp,
        "alerts": alerts,
        "results": [r.to_dict() for r in results],
        "fetch_errors": ds.errors,
        "fed_actions": manual.get("fed_actions") or [],
        "upcoming": upcoming_events(asof) if mode == "weekly" else [],
        "stale_ratio": round(sum(r.status == "stale" for r in results) / max(len(results), 1), 3),
    }
    if extra:
        run.update(extra)
    return run


def write_outputs(run: dict):
    OUT.mkdir(exist_ok=True)
    (OUT / "run.json").write_text(json.dumps(run, indent=2, default=str))
    (OUT / "report.md").write_text(render.to_markdown(run))
    rules = {s["id"]: s.get("rule", {}) for s in load_yaml("signals.yaml")["signals"]}
    try:
        from . import charts
        imgs = charts.render_stages(run["results"], rules, OUT / "charts", lambda r: render.fmt(r["value"], r["unit"]))
    except Exception as exc:  # noqa: BLE001  (charts are cosmetic; never fail the run over them)
        print(f"warning: chart rendering failed, using text sparklines: {exc}", file=sys.stderr)
        imgs = []
    (OUT / "report.html").write_text(render.to_html(run, {i["id"]: f"charts/{i['id']}.png" for i in imgs}))
    # E-mail: one inline PNG per stage (Gmail allows at most 10 attachments), referenced as cid:attN by position
    attachments = [{"filename": f"{i['id']}.png", "mimeType": "image/png", "inline": True,
                    "content": f"sha256:{i['sha256']}:{i['path']}"} for i in imgs]
    should_send = run["mode"] == "weekly" or bool(run["alerts"])
    (OUT / "email.json").write_text(json.dumps({
        "should_send": should_send,
        "subject": render.subject(run),
        "html": render.email_safe(render.to_html(run, {i["id"]: f"cid:att{n}" for n, i in enumerate(imgs)})),
        "text": render.email_safe(render.to_text(run)),
        "attachments": attachments,
    }, indent=2))


# ---------------------------------------------------------------- commands
def cmd_verify(args) -> int:
    sig_cfg = load_yaml("signals.yaml")["signals"]
    ds = DataStore(years=1, today=_today())
    ds.prefetch(sig_cfg)
    print(f"{'source':34} {'last date':12} {'last value':>12} {'age(d)':>7}")
    for k, s in sorted(ds.series.items()):
        if k.endswith("|adj"):
            continue
        age = (pd.Timestamp(ds.today) - s.index[-1]).days
        print(f"{k:34} {s.index[-1].strftime('%Y-%m-%d'):12} {s.iloc[-1]:>12.4f} {age:>7}")
    for k, v in sorted(ds.errors.items()):
        print(f"{k:34} ERROR {v}")
    print(f"\n{sum(not k.endswith('|adj') for k in ds.series)} ok, {len(ds.errors)} failed")
    return 1 if ds.errors else 0


def cmd_run(args) -> int:
    asof = dt.date.fromisoformat(args.asof) if args.asof else _today()
    settings = load_yaml("settings.yaml")
    ds = DataStore(years=int(settings.get("history_years", 3)), today=asof)
    sig_cfg = load_yaml("signals.yaml")["signals"]
    if args.mode == "daily":
        sig_cfg = [s for s in sig_cfg if s["stage"] in (2, 4)]
    ds.prefetch(sig_cfg)
    ds.save(OUT / "cache.pkl")
    extra = {}
    if args.mode == "weekly" and not args.no_edgar:
        extra["edgar_scan"] = edgar_scan(settings, asof)
        (OUT / "edgar_scan.json").write_text(json.dumps(extra["edgar_scan"], indent=2))
    (OUT / "run_meta.json").write_text(json.dumps({"mode": args.mode, "asof": asof.isoformat(), **extra}, default=str))
    run = build_run(ds, args.mode, asof, extra)
    write_outputs(run)
    _print_summary(run)
    if run["stale_ratio"] > float(settings.get("stale_fail_ratio", 0.25)):
        print(f"\nFAIL: {run['stale_ratio']:.0%} of signals stale (limit {settings.get('stale_fail_ratio')})", file=sys.stderr)
        return 2
    return 0


def cmd_finalize(args) -> int:
    meta = json.loads((OUT / "run_meta.json").read_text())
    ds = DataStore.load(OUT / "cache.pkl")
    asof = dt.date.fromisoformat(meta["asof"])
    extra = {k: v for k, v in meta.items() if k not in ("mode", "asof")}
    summary_path = Path(args.summary) if args.summary else OUT / "summary.md"
    if summary_path.exists():
        extra["summary"] = summary_path.read_text()
    run = build_run(ds, meta["mode"], asof, extra)
    write_outputs(run)
    if not args.dry_run:
        run_ts = run["generated_utc"]
        run_id = f"{asof.isoformat()}-{meta['mode']}-{run_ts[11:19].replace(':', '')}"
        from .signals import Result
        results = [Result(**r) for r in run["results"]]
        history.append_run(DATA, run_id, run_ts, meta["mode"], asof.isoformat(), results, run["composite"], ds.errors)
        if meta["mode"] == "weekly":
            REPORTS.mkdir(exist_ok=True)
            (REPORTS / f"{asof.isoformat()}.md").write_text(render.to_markdown(run))
    _print_summary(run)
    email = json.loads((OUT / "email.json").read_text())
    print(f"\nshould_send={email['should_send']}  subject={email['subject']}")
    return 0


def cmd_replay(args) -> int:
    """Score past dates (default: weekly Fridays) to sanity-check thresholds. Manual/judgement signals are n/a."""
    end = dt.date.fromisoformat(args.end) if args.end else _today()
    start = dt.date.fromisoformat(args.start)
    years = max(3, (end - start).days // 365 + 2)
    ds = DataStore(years=years, today=end)
    sig_cfg = [s for s in load_yaml("signals.yaml")["signals"] if s["source"]["type"] not in ("manual", "judgement")]
    ds.prefetch(sig_cfg)
    comp_cfg = load_yaml("composite.yaml")
    rows = []
    for d in pd.date_range(start, end, freq=args.freq):
        res = score_all(sig_cfg, ds, {}, d.date(), 2)
        c = comp_mod.composite(res, comp_cfg)
        row = {"date": d.date().isoformat(), "composite": c["level"]}
        row.update({r.id: r.status for r in res})
        rows.append(row)
    df = pd.DataFrame(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"wrote {out} ({len(df)} dates)\n")
    counts = {c: df[c].value_counts().to_dict() for c in df.columns if c not in ("date", "composite")}
    print(f"{'signal':20} {'green':>6} {'amber':>6} {'red':>6} {'stale':>6}")
    for k, v in counts.items():
        print(f"{k:20} {v.get('green', 0):>6} {v.get('amber', 0):>6} {v.get('red', 0):>6} {v.get('stale', 0):>6}")
    print("\ncomposite level counts:", df["composite"].value_counts().sort_index().to_dict())
    return 0


def _print_summary(run: dict):
    c = run["composite"]
    print(f"[{run['mode']}] as of {run['asof']}: composite = {c['name']} (level {c['level']})")
    for r in run["results"]:
        v = render.fmt(r["value"], r["unit"])
        extra = r["error"] or r["note"]
        print(f"  S{r['stage']} {r['status']:6} {r['id']:24} {v:>12}  {r['spark']}  {extra}")
    for a in run["alerts"]:
        print("  ALERT:", render._alert_text(a))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="tracker")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="fetch every source once; non-zero exit if any fails")
    r = sub.add_parser("run", help="fetch + score; writes out/ (no history)")
    r.add_argument("--mode", choices=["weekly", "daily"], default="weekly")
    r.add_argument("--asof")
    r.add_argument("--no-edgar", action="store_true")
    f = sub.add_parser("finalize", help="re-score with manual inputs, render, append history")
    f.add_argument("--summary")
    f.add_argument("--dry-run", action="store_true")
    rp = sub.add_parser("replay", help="score historical dates to tune thresholds")
    rp.add_argument("--start", required=True)
    rp.add_argument("--end")
    rp.add_argument("--freq", default="W-FRI")
    rp.add_argument("--out", default="data/replay.csv")
    args = p.parse_args(argv)
    return {"verify": cmd_verify, "run": cmd_run, "finalize": cmd_finalize, "replay": cmd_replay}[args.cmd](args)
