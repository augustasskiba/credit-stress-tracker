"""Append-only CSV history (committed to git) and alert diffing."""
from __future__ import annotations

import csv
from pathlib import Path

OBS_FIELDS = ["run_id", "run_ts", "mode", "signal_id", "stage", "last_date", "value", "status"]
RUN_FIELDS = ["run_id", "run_ts", "mode", "asof", "composite_level", "composite_name",
              "n_red", "n_amber", "n_stale", "errors"]


def _append(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def previous_state(data_dir: Path, mode: str, exclude_prefix: str = "") -> tuple[dict[str, str], int | None]:
    """Latest known status per signal (any mode) and the composite level of the last run of `mode`.

    exclude_prefix skips rows of the run currently being (re)finalised."""
    runs = [r for r in _read(data_dir / "runs.csv") if not (exclude_prefix and r["run_id"].startswith(exclude_prefix))]
    if not runs:
        return {}, None
    status: dict[str, str] = {}
    for r in _read(data_dir / "observations.csv"):   # file is chronological; later rows win
        if exclude_prefix and r["run_id"].startswith(exclude_prefix):
            continue
        status[r["signal_id"]] = r["status"]
    same = [r for r in runs if r["mode"] == mode]
    return status, (int(same[-1]["composite_level"]) if same else None)


def compute_alerts(results, comp: dict, prev_status: dict, prev_level: int | None) -> list[dict]:
    alerts = []
    for r in results:
        if r.status == "red" and prev_status.get(r.id) != "red":
            alerts.append({"type": "new_red", "signal": r.id, "name": r.name, "value": r.value,
                           "unit": r.unit, "last_date": r.last_date, "previous": prev_status.get(r.id, "none")})
    if prev_level is not None and comp["level"] > prev_level:
        alerts.append({"type": "composite_up", "from": prev_level, "to": comp["level"], "name": comp["name"]})
    return alerts


def _drop_run_key(path: Path, fields: list[str], prefix: str):
    """Remove rows whose run_id starts with prefix (re-running finalize for the same date/mode)."""
    rows = _read(path)
    keep = [r for r in rows if not r["run_id"].startswith(prefix)]
    if len(keep) != len(rows):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(keep)


def append_run(data_dir: Path, run_id: str, run_ts: str, mode: str, asof: str, results, comp: dict, errors: dict):
    # Idempotent per (as-of date, mode): a re-run of finalize replaces that run's rows; older runs are never touched.
    prefix = f"{asof}-{mode}-"
    _drop_run_key(data_dir / "observations.csv", OBS_FIELDS, prefix)
    _drop_run_key(data_dir / "runs.csv", RUN_FIELDS, prefix)
    _append(data_dir / "observations.csv", OBS_FIELDS, [
        {"run_id": run_id, "run_ts": run_ts, "mode": mode, "signal_id": r.id, "stage": r.stage,
         "last_date": r.last_date or "", "value": "" if r.value is None else round(r.value, 4), "status": r.status}
        for r in results
    ])
    _append(data_dir / "runs.csv", RUN_FIELDS, [{
        "run_id": run_id, "run_ts": run_ts, "mode": mode, "asof": asof,
        "composite_level": comp["level"], "composite_name": comp["name"],
        "n_red": sum(r.status == "red" for r in results),
        "n_amber": sum(r.status == "amber" for r in results),
        "n_stale": sum(r.status == "stale" for r in results),
        "errors": "; ".join(f"{k}: {v}" for k, v in errors.items())[:2000],
    }])


# ---------------------------------------------------------------- EDGAR keyword scan history
EDGAR_FIELDS = ["asof", "keyword", "group", "total"]
HIT_FIELDS = ["asof", "keyword", "group", "company", "form", "filed", "url"]


def _rewrite_without(path: Path, fields: list[str], asof: str):
    rows = _read(path)
    keep = [r for r in rows if r["asof"] != asof]
    if len(keep) != len(rows):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(keep)


def append_edgar(data_dir: Path, asof: str, scan: dict):
    """Store keyword totals and the filings returned, one set per as-of date (a same-day re-run replaces it)."""
    _rewrite_without(data_dir / "edgar_scan.csv", EDGAR_FIELDS, asof)
    _rewrite_without(data_dir / "edgar_hits.csv", HIT_FIELDS, asof)
    totals, hits = [], []
    for kw, groups in (scan.get("keywords") or {}).items():
        for g, v in groups.items():
            totals.append({"asof": asof, "keyword": kw, "group": g, "total": v.get("total", 0)})
            for i in v.get("items", []):
                hits.append({"asof": asof, "keyword": kw, "group": g, **{k: i.get(k, "") for k in ("company", "form", "filed", "url")}})
    _append(data_dir / "edgar_scan.csv", EDGAR_FIELDS, totals)
    _append(data_dir / "edgar_hits.csv", HIT_FIELDS, hits)


def previous_edgar(data_dir: Path, asof: str) -> dict | None:
    """The latest scan before `asof`: {'asof', 'totals': {(kw, group): n}, 'seen': set of filing URLs seen in any earlier scan}."""
    rows = [r for r in _read(data_dir / "edgar_scan.csv") if r["asof"] < asof]
    if not rows:
        return None
    last = max(r["asof"] for r in rows)
    totals = {(r["keyword"], r["group"]): int(r["total"]) for r in rows if r["asof"] == last}
    seen = {r["url"] for r in _read(data_dir / "edgar_hits.csv") if r["asof"] < asof and r["url"]}
    return {"asof": last, "totals": totals, "seen": seen}


def compare_edgar(scan: dict, prev: dict | None) -> dict:
    """Annotate a scan with prev_total / delta / new filings versus the previous scan (returns a copy)."""
    import copy
    out = copy.deepcopy(scan)
    out["prev_asof"] = prev["asof"] if prev else None
    for kw, groups in (out.get("keywords") or {}).items():
        for g, v in groups.items():
            pt = prev["totals"].get((kw, g)) if prev else None
            v["prev_total"] = pt
            v["delta"] = None if pt is None else v.get("total", 0) - pt
            v["new_items"] = [i for i in v.get("items", []) if i.get("url") and i["url"] not in prev["seen"]] if prev else []
    return out
