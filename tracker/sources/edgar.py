"""SEC EDGAR: ticker->CIK map, XBRL NAV per share, and full-text keyword scan."""
from __future__ import annotations

import datetime as dt
import time
from functools import lru_cache

import pandas as pd

from .http import get, sec_user_agent


def _sec_get(url, params=None):
    time.sleep(0.15)  # stay well under SEC's 10 req/s
    return get(url, params=params, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"})


@lru_cache(maxsize=1)
def ticker_map() -> dict[str, int]:
    data = _sec_get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}


def cik(ticker: str) -> int:
    m = ticker_map()
    t = ticker.upper().replace(".", "-")
    if t not in m:
        raise KeyError(f"EDGAR: no CIK for ticker {ticker}")
    return m[t]


NAV_TAGS = ["NetAssetValuePerShare"]


def fetch_nav_per_share(ticker: str) -> pd.Series:
    """NAV per share indexed by *filing* date (so it is only used once public)."""
    c = cik(ticker)
    last_err = None
    for tag in NAV_TAGS:
        try:
            d = _sec_get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{c:010d}/us-gaap/{tag}.json").json()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        rows = []
        for unit, facts in d.get("units", {}).items():
            for f in facts:
                if f.get("form") in ("10-Q", "10-K", "10-Q/A", "10-K/A") and f.get("filed") and f.get("end"):
                    rows.append((pd.Timestamp(f["filed"]), pd.Timestamp(f["end"]), float(f["val"])))
        if rows:
            df = pd.DataFrame(rows, columns=["filed", "end", "val"])
            # For each filing, keep the value for the latest period end it reports
            df = df.sort_values(["filed", "end"]).groupby("filed").tail(1)
            s = pd.Series(df["val"].values, index=df["filed"], name=f"{ticker}_nav")
            return s[~s.index.duplicated(keep="last")].sort_index()
    raise ValueError(f"EDGAR NAV per share not found for {ticker}: {last_err}")


def full_text_hits(query: str, ciks: list[int], start: dt.date, end: dt.date, forms: list[str]) -> dict:
    params = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "forms": ",".join(forms),
        "ciks": ",".join(f"{c:010d}" for c in ciks),
    }
    d = _sec_get("https://efts.sec.gov/LATEST/search-index", params=params).json()
    hits = d.get("hits", {})
    items = []
    for h in hits.get("hits", [])[:10]:
        src = h.get("_source", {})
        adsh, _, fname = h.get("_id", "").partition(":")
        cik0 = (src.get("ciks") or ["0"])[0].lstrip("0")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik0}/{adsh.replace('-', '')}/{fname}" if adsh else ""
        items.append({
            "company": (src.get("display_names") or ["?"])[0].split("  (")[0],
            "form": src.get("form"),
            "filed": src.get("file_date"),
            "url": url,
        })
    return {"total": hits.get("total", {}).get("value", 0), "items": items}
