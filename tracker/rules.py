"""Generic, config-driven threshold evaluation."""
from __future__ import annotations

import operator

import pandas as pd

from .calendar_utils import in_month_end_window

LEVEL = {"green": 0, "amber": 1, "red": 2}
OPS = {"gt": operator.gt, "lt": operator.lt, "ge": operator.ge, "le": operator.le}


def normalize_rule(rule: dict) -> dict:
    """Expand the {op, amber, red} shorthand into {amber: [cond], red: [cond]}."""
    if "op" in rule:
        return {
            "amber": [{"op": rule["op"], "value": rule["amber"]}],
            "red": [{"op": rule["op"], "value": rule["red"]}],
        }
    return {"amber": list(rule.get("amber", [])), "red": list(rule.get("red", []))}


def eval_cond(s: pd.Series, cond: dict) -> bool:
    s = s.dropna()
    if s.empty:
        return False

    if "rising" in cond:
        n = int(cond["rising"])
        if len(s) < n + 1:
            return False
        return bool((s.diff().tail(n) > 0).all())

    x = s
    if "diff" in cond:
        x = x.diff(int(cond["diff"])).dropna()
    if cond.get("exclude") == "month_end":
        x = x[~in_month_end_window(x.index).values]
    if x.empty:
        return False

    hit = OPS[cond["op"]](x, cond["value"])

    if "count" in cond:
        within = int(cond.get("within", cond["count"]))
        return int(hit.tail(within).sum()) >= int(cond["count"])
    if "persist" in cond:
        n = int(cond["persist"])
        tail = hit.tail(n)
        return len(tail) == n and bool(tail.all())
    return bool(hit.iloc[-1])


def evaluate(s: pd.Series, rule: dict) -> str:
    r = normalize_rule(rule)
    if any(eval_cond(s, c) for c in r["red"]):
        return "red"
    if any(eval_cond(s, c) for c in r["amber"]):
        return "amber"
    return "green"


def worse_or_equal(status: str, target: str) -> bool:
    return status in LEVEL and LEVEL[status] >= LEVEL[target]
