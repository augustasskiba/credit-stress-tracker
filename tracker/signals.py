"""Turn signal definitions + raw data into value series and scored results."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import pandas as pd

from .calendar_utils import in_month_end_window
from .data import DataStore
from .rules import evaluate

SPARK = "▁▂▃▄▅▆▇█"


@dataclass
class Result:
    id: str
    stage: int
    name: str
    unit: str
    status: str                  # green | amber | red | stale | n/a
    value: float | None = None
    last_date: str | None = None
    chg_1w: float | None = None
    chg_3m: float | None = None
    spark: str = ""
    note: str = ""
    error: str = ""
    history: list = field(default_factory=list)   # [(date, value)] last ~13 weeks, for charts

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- raw series
def build_raw(src: dict, ds: DataStore, manual: dict) -> pd.Series:
    t = src["type"]
    if t == "fred":
        s = ds.fred(src["series"])
    elif t == "yahoo":
        s = ds.yahoo(src["ticker"], adjusted=bool(src.get("adjusted", False)))
    elif t == "ratio":
        a, b = ds.yahoo(src["a"], adjusted=True), ds.yahoo(src["b"], adjusted=True)
        s = (a / b.reindex(a.index).ffill()).dropna()
    elif t == "nyfed":
        s = ds.nyfed(src["rate"])
    elif t == "srf":
        s = ds.srf()
    elif t == "spread":
        a = build_raw(src["a"], ds, manual)
        b = build_raw(src["b"], ds, manual)
        b = b.reindex(a.index.union(b.index)).sort_index().ffill().reindex(a.index)
        s = (a - b).dropna()
    elif t == "bdc_pnav":
        px = ds.yahoo(src["ticker"])
        nav = ds.nav(src["ticker"])
        nav_d = nav.reindex(px.index.union(nav.index)).sort_index().ffill().reindex(px.index)
        s = (px / nav_d).dropna()
    elif t == "forced_selling":
        rets = pd.concat([ds.yahoo(x, adjusted=True).pct_change() * 100 for x in src["tickers"]], axis=1).dropna()
        s = (rets < src.get("threshold", -1)).all(axis=1).astype(float)
    elif t == "manual":
        rows = (manual.get("quarterly") or {}).get(src["key"]) or []
        if not rows:
            raise LookupError("no manual data yet: add rows to config/manual_inputs.yaml")
        s = pd.Series({pd.Timestamp(r["date"]): float(r["value"]) for r in rows}).sort_index()
    else:
        raise ValueError(f"unknown source type {t}")
    if "scale" in src:
        s = s * float(src["scale"])
    return s


def apply_transforms(s: pd.Series, transforms: list[dict] | None) -> pd.Series:
    for tr in transforms or []:
        (k, v), = tr.items()
        if k == "pct_change":
            s = s.pct_change(int(v), fill_method=None) * 100
        elif k == "diff":
            s = s.diff(int(v))
        elif k == "drawdown":
            s = (s / s.rolling(int(v), min_periods=1).max() - 1) * 100
        elif k == "rolling_sum":
            s = s.rolling(int(v), min_periods=1).sum()
        elif k == "scale":
            s = s * float(v)
        else:
            raise ValueError(f"unknown transform {k}")
    return s.dropna()


def value_series(sig: dict, ds: DataStore, manual: dict) -> pd.Series:
    return apply_transforms(build_raw(sig["source"], ds, manual), sig.get("transform"))


# ---------------------------------------------------------------- helpers
def _asof_value(s: pd.Series, when: pd.Timestamp):
    s2 = s[s.index <= when]
    return None if s2.empty else float(s2.iloc[-1])


def sparkline(values: list[float]) -> str:
    vals = [v for v in values if v is not None and pd.notna(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return SPARK[3] * len(vals)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in vals)


def _spark_points(s: pd.Series, n: int) -> pd.Series:
    spacing = s.index.to_series().diff().dt.days.median() if len(s) > 2 else 1
    if spacing and spacing > 10:          # monthly / quarterly data: last n observations
        return s.tail(n)
    return s.resample("W-FRI").last().dropna().tail(n)


# ---------------------------------------------------------------- scoring
def score_signal(sig: dict, ds: DataStore, manual: dict, asof: dt.date, spark_n: int = 13) -> Result:
    base = dict(id=sig["id"], stage=int(sig["stage"]), name=sig["name"], unit=sig.get("unit", ""))
    asof_ts = pd.Timestamp(asof)
    max_age = int(sig.get("max_age_days", 7))
    src = sig["source"]

    if src["type"] == "judgement":
        j = (manual.get("judgements") or {}).get(src["key"]) or {}
        status, as_of = j.get("status"), j.get("as_of")
        if status not in ("green", "amber", "red") or not as_of:
            return Result(**base, status="n/a", note=j.get("note") or "Not reviewed yet.")
        age = (asof_ts - pd.Timestamp(as_of)).days
        st = "stale" if age > max_age else status
        return Result(**base, status=st, last_date=str(as_of)[:10], note=j.get("note", ""))

    try:
        s = value_series(sig, ds, manual)
    except LookupError as exc:
        return Result(**base, status="n/a", note=str(exc))
    except Exception as exc:  # noqa: BLE001
        return Result(**base, status="stale", error=str(exc))

    s = s[s.index <= asof_ts]
    if s.empty:
        return Result(**base, status="stale", error="no observations up to as-of date")

    last_date = s.index[-1]
    value = float(s.iloc[-1])
    age = (asof_ts - last_date).days
    status = evaluate(s, sig["rule"])
    note = ""
    if age > max_age:
        note = f"last observation {age} days old (max {max_age})"
        status = "stale"

    flag = sig.get("flag_month_end")
    if flag is not None and status != "stale":
        win = in_month_end_window(s.index[-3:])
        recent = s.iloc[-3:][win.values]
        if not recent.empty and (recent > flag).any():
            note = (note + "; " if note else "") + f"month/quarter-end spike (max {recent.max():.1f}) flagged, not alerted"

    v1w = _asof_value(s, last_date - pd.Timedelta(days=7))
    v3m = _asof_value(s, last_date - pd.Timedelta(days=91))
    pts = _spark_points(s, spark_n)
    return Result(
        **base,
        status=status,
        value=value,
        last_date=last_date.strftime("%Y-%m-%d"),
        chg_1w=None if v1w is None else value - v1w,
        chg_3m=None if v3m is None else value - v3m,
        spark=sparkline(list(pts.values)),
        note=note,
        history=[(d.strftime("%Y-%m-%d"), round(float(v), 4)) for d, v in pts.items()],
    )


def score_all(signals: list[dict], ds: DataStore, manual: dict, asof: dt.date, spark_n: int = 13) -> list[Result]:
    return [score_signal(sig, ds, manual, asof, spark_n) for sig in signals]
