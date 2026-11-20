"""NY Fed Markets API: secured reference rates and repo operations (Standing Repo Facility)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .http import get

BASE = "https://markets.newyorkfed.org/api"


def _chunks(start: dt.date, end: dt.date, days: int = 365):
    cur = start
    while cur <= end:
        nxt = min(cur + dt.timedelta(days=days - 1), end)
        yield cur, nxt
        cur = nxt + dt.timedelta(days=1)


def fetch_rate(rate: str, start: dt.date, end: dt.date) -> pd.Series:
    """rate: sofr | tgcr | bgcr. Returns percent, indexed by effective date."""
    rows = []
    for a, b in _chunks(start, end):
        r = get(f"{BASE}/rates/secured/{rate}/search.json",
                params={"startDate": a.isoformat(), "endDate": b.isoformat()})
        rows += r.json().get("refRates", [])
    if not rows:
        raise ValueError(f"NY Fed {rate}: no data")
    s = pd.Series({pd.Timestamp(x["effectiveDate"]): float(x["percentRate"]) for x in rows}, name=rate)
    return s.sort_index()


def fetch_srf(start: dt.date, end: dt.date) -> pd.Series:
    """Daily total accepted in repo (SRF) operations, $bn. Days with operations but zero take-up are 0."""
    ops = []
    for a, b in _chunks(start, end, days=180):
        r = get(f"{BASE}/rp/results/search.json",
                params={"startDate": a.isoformat(), "endDate": b.isoformat(), "operationTypes": "Repo"})
        ops += r.json().get("repo", {}).get("operations", [])
    if not ops:
        raise ValueError("NY Fed repo operations: no data")
    df = pd.DataFrame(ops)
    df = df[df["operationType"].str.lower() == "repo"]
    df["date"] = pd.to_datetime(df["operationDate"])
    df["amt"] = pd.to_numeric(df["totalAmtAccepted"], errors="coerce").fillna(0) / 1e9
    s = df.groupby("date")["amt"].sum()
    s.name = "srf_bn"
    return s.sort_index()
