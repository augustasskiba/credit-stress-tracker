"""Composite reading from config/composite.yaml."""
from __future__ import annotations

from .rules import worse_or_equal


def _cond(c, by_id: dict, results) -> bool:
    if c == "always":
        return True
    if "any_of" in c:
        return any(_cond(x, by_id, results) for x in c["any_of"])
    if "all_of" in c:
        return all(_cond(x, by_id, results) for x in c["all_of"])
    if "stage_count" in c:
        sc = c["stage_count"]
        n = sum(1 for r in results if r.stage == sc["stage"] and worse_or_equal(r.status, sc["status"]))
        return n >= sc["min"]
    if "signal" in c:
        sg = c["signal"]
        r = by_id.get(sg["id"])
        return r is not None and worse_or_equal(r.status, sg["status"])
    raise ValueError(f"unknown composite condition: {c}")


def composite(results, cfg: dict) -> dict:
    by_id = {r.id: r for r in results}
    for lvl in sorted(cfg["levels"], key=lambda x: -x["level"]):
        if _cond(lvl["when"], by_id, results):
            out = {"level": lvl["level"], "name": lvl["name"]}
            break
    # Watch notes: reds outside stages 1-2 that did not escalate the composite on their own
    watch = [r.id for r in results if r.stage >= 3 and r.status == "red"]
    out["watch"] = watch if out["level"] < 2 else []
    return out
