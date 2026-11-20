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


def previous_state(data_dir: Path, mode: str) -> tuple[dict[str, str], int | None]:
    """Latest known status per signal (any mode) and the composite level of the last run of `mode`."""
    runs = _read(data_dir / "runs.csv")
    if not runs:
        return {}, None
    status: dict[str, str] = {}
    for r in _read(data_dir / "observations.csv"):   # file is chronological; later rows win
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


def append_run(data_dir: Path, run_id: str, run_ts: str, mode: str, asof: str, results, comp: dict, errors: dict):
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
