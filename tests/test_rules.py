import pandas as pd

from tracker.calendar_utils import in_month_end_window
from tracker.composite import composite
from tracker.rules import eval_cond, evaluate
from tracker.signals import Result, apply_transforms, sparkline


def s(values, start="2026-01-05", freq="B"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def test_shorthand_gt():
    rule = {"op": "gt", "amber": 400, "red": 500}
    assert evaluate(s([300, 350]), rule) == "green"
    assert evaluate(s([300, 450]), rule) == "amber"
    assert evaluate(s([300, 501]), rule) == "red"


def test_shorthand_lt():
    rule = {"op": "lt", "amber": 0.9, "red": 0.8}
    assert evaluate(s([1.0, 0.85]), rule) == "amber"
    assert evaluate(s([1.0, 0.75]), rule) == "red"


def test_persist():
    c = {"op": "gt", "value": 30, "persist": 5}
    assert not eval_cond(s([31, 31, 31, 31]), c)
    assert eval_cond(s([20, 31, 31, 31, 31, 31]), c)
    assert not eval_cond(s([31, 31, 31, 29, 31, 31]), c)


def test_count_within():
    c = {"op": "gt", "value": 25, "count": 3, "within": 10}
    assert eval_cond(s([30, 0, 30, 0, 0, 30, 0]), c)
    assert not eval_cond(s([30, 0, 30, 0, 0, 0, 0]), c)


def test_diff():
    c = {"op": "gt", "value": 0.25, "diff": 8}
    assert eval_cond(s([-0.5] * 8 + [-0.2], freq="W-FRI"), c)
    assert not eval_cond(s([-0.5] * 8 + [-0.4], freq="W-FRI"), c)


def test_rising():
    assert eval_cond(s([1, 2, 3], freq="QE"), {"rising": 2})
    assert not eval_cond(s([1, 2, 3], freq="QE"), {"rising": 3})
    assert eval_cond(s([1, 2, 3, 4], freq="QE"), {"rising": 3})
    assert not eval_cond(s([1, 3, 2, 4], freq="QE"), {"rising": 2})


def test_month_end_window_and_exclusion():
    idx = pd.DatetimeIndex(["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"])
    win = in_month_end_window(idx).tolist()
    assert win == [False, True, True, True, False]
    # spike only inside the window -> not amber
    x = pd.Series([1, 20, 20, 20, 1], index=idx, dtype=float)
    c = {"op": "gt", "value": 5, "persist": 3, "exclude": "month_end"}
    assert not eval_cond(x, c)


def test_transforms():
    x = s([100, 110, 99, 88])
    dd = apply_transforms(x, [{"drawdown": 252}])
    assert round(dd.iloc[-1], 1) == -20.0
    pc = apply_transforms(x, [{"pct_change": 1}])
    assert round(pc.iloc[0], 1) == 10.0  # first value dropped (NaN)


def test_sparkline():
    assert sparkline([1, 2, 3]) == "▁▄█"
    assert sparkline([1]) == ""


def _r(id_, stage, status):
    return Result(id=id_, stage=stage, name=id_, unit="", status=status)


CFG = {"levels": [
    {"level": 3, "name": "Systemic", "when": {"any_of": [{"stage_count": {"stage": 4, "status": "red", "min": 2}}]}},
    {"level": 2, "name": "Spreading", "when": {"any_of": [
        {"stage_count": {"stage": 3, "status": "red", "min": 2}},
        {"all_of": [{"signal": {"id": "sloos_ci", "status": "red"}},
                    {"any_of": [{"signal": {"id": "kre", "status": "red"}}]}]}]}},
    {"level": 1, "name": "Grind", "when": {"any_of": [{"stage_count": {"stage": 1, "status": "amber", "min": 1}}]}},
    {"level": 0, "name": "Calm", "when": "always"},
]}


def test_composite_levels():
    assert composite([_r("a", 1, "green")], CFG)["level"] == 0
    assert composite([_r("a", 1, "amber")], CFG)["level"] == 1
    assert composite([_r("sloos_ci", 3, "red"), _r("kre", 3, "red")], CFG)["level"] == 2
    assert composite([_r("x", 4, "red"), _r("y", 4, "red"), _r("a", 1, "amber")], CFG)["level"] == 3
    # stale never counts
    assert composite([_r("x", 4, "stale"), _r("y", 4, "red")], CFG)["level"] == 0
