"""Yahoo Finance closes via yfinance (unofficial; retried, failures mark signals stale)."""
from __future__ import annotations

import logging
import time

import pandas as pd

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def fetch_closes(tickers: list[str], years: int = 3, retries: int = 3) -> dict[str, pd.Series]:
    """Returns {"T": raw close, "T|adj": dividend-adjusted (total-return) close}."""
    import yfinance as yf

    out: dict[str, pd.Series] = {}
    missing = list(dict.fromkeys(tickers))
    for attempt in range(retries):
        if not missing:
            break
        try:
            df = yf.download(missing, period=f"{years}y", interval="1d", auto_adjust=False,
                             progress=False, threads=True, group_by="column")
        except Exception:  # noqa: BLE001
            df = None
        if df is not None and not df.empty:
            def col(name):
                if isinstance(df.columns, pd.MultiIndex):
                    return df[name]
                return df[[name]].rename(columns={name: missing[0]})
            raw, adj = col("Close"), col("Adj Close")
            for t in list(missing):
                if t in raw.columns:
                    s = raw[t].dropna()
                    if not s.empty:
                        idx = pd.to_datetime(s.index).tz_localize(None).normalize()
                        s.index = idx
                        out[t] = s.rename(t)
                        a = adj[t].dropna() if t in adj.columns else s
                        a.index = pd.to_datetime(a.index).tz_localize(None).normalize()
                        out[t + "|adj"] = a.rename(t)
                        missing.remove(t)
        if missing and attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return out
