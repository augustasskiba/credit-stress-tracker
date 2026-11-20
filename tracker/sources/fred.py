"""FRED series via the keyless fredgraph.csv endpoint."""
from __future__ import annotations

import io

import pandas as pd

from .http import get

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch(series_id: str, start: str | None = None) -> pd.Series:
    params = {"id": series_id}
    if start:
        params["cosd"] = start
    r = get(URL, params=params)
    text = r.text
    if not text.lower().startswith("observation_date") and not text.startswith("DATE"):
        raise ValueError(f"FRED {series_id}: unexpected response (bad series id?)")
    df = pd.read_csv(io.StringIO(text), na_values=["."])
    df.columns = ["date", "value"]
    s = pd.Series(pd.to_numeric(df["value"], errors="coerce").values,
                  index=pd.to_datetime(df["date"]), name=series_id).dropna()
    if s.empty:
        raise ValueError(f"FRED {series_id}: no observations")
    return s
