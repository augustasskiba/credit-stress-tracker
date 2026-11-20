"""DataStore: fetches every raw series once per run, records errors, and can be cached to disk."""
from __future__ import annotations

import datetime as dt
import pickle
import traceback
from pathlib import Path

import pandas as pd

from .sources import edgar, fred, nyfed, yahoo


def _walk_sources(src: dict):
    yield src
    for k in ("a", "b"):
        if isinstance(src.get(k), dict):
            yield from _walk_sources(src[k])


class DataStore:
    def __init__(self, years: int = 3, today: dt.date | None = None):
        self.today = today or dt.date.today()
        self.start = self.today - dt.timedelta(days=int(365.25 * years) + 30)
        self.years = years
        self.series: dict[str, pd.Series] = {}
        self.errors: dict[str, str] = {}

    # ---------- generic ----------
    def _get(self, key: str, fn):
        if key in self.series:
            return self.series[key]
        if key in self.errors:
            raise RuntimeError(self.errors[key])
        try:
            s = fn()
            self.series[key] = s
            return s
        except Exception as exc:  # noqa: BLE001
            self.errors[key] = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(self.errors[key]) from exc

    def fred(self, sid: str) -> pd.Series:
        return self._get(f"fred:{sid}", lambda: fred.fetch(sid, start=self.start.isoformat()))

    def yahoo(self, ticker: str, adjusted: bool = False) -> pd.Series:
        """Raw close by default; adjusted=True gives the dividend-adjusted (total-return) close."""
        base = f"yahoo:{ticker}"
        if base not in self.series and base not in self.errors:
            self.prefetch_yahoo([ticker])
        key = base + ("|adj" if adjusted else "")
        if key not in self.series and base in self.series:
            key = base
        return self._get(key, lambda: (_ for _ in ()).throw(ValueError(f"Yahoo: no data for {ticker}")))

    def prefetch_yahoo(self, tickers: list[str]):
        need = [t for t in tickers if f"yahoo:{t}" not in self.series]
        if not need:
            return
        got = yahoo.fetch_closes(need, years=self.years)
        for t in need:
            if t in got:
                self.series[f"yahoo:{t}"] = got[t]
                self.series[f"yahoo:{t}|adj"] = got.get(t + "|adj", got[t])
            else:
                self.errors[f"yahoo:{t}"] = f"ValueError: Yahoo returned no data for {t}"

    def nyfed(self, rate: str) -> pd.Series:
        return self._get(f"nyfed:{rate}", lambda: nyfed.fetch_rate(rate, self.start, self.today))

    def srf(self) -> pd.Series:
        return self._get("nyfed:srf", lambda: nyfed.fetch_srf(self.start, self.today))

    def nav(self, ticker: str) -> pd.Series:
        return self._get(f"edgar_nav:{ticker}", lambda: edgar.fetch_nav_per_share(ticker))

    # ---------- prefetch everything a signal list needs ----------
    def prefetch(self, signals: list[dict]):
        tickers: list[str] = []
        for sig in signals:
            for src in _walk_sources(sig["source"]):
                t = src.get("type")
                if t == "yahoo":
                    tickers.append(src["ticker"])
                elif t == "ratio":
                    tickers += [src["a"], src["b"]]
                elif t == "bdc_pnav":
                    tickers.append(src["ticker"])
                elif t == "forced_selling":
                    tickers += src["tickers"]
        self.prefetch_yahoo(list(dict.fromkeys(tickers)))
        for sig in signals:
            for src in _walk_sources(sig["source"]):
                t = src.get("type")
                try:
                    if t == "fred":
                        self.fred(src["series"])
                    elif t == "nyfed":
                        self.nyfed(src["rate"])
                    elif t == "srf":
                        self.srf()
                    elif t == "bdc_pnav":
                        self.nav(src["ticker"])
                except RuntimeError:
                    pass  # recorded in self.errors

    # ---------- persistence between `run` and `finalize` ----------
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"today": self.today, "years": self.years, "series": self.series, "errors": self.errors}, f)

    @classmethod
    def load(cls, path: Path) -> "DataStore":
        with open(path, "rb") as f:
            d = pickle.load(f)
        ds = cls(years=d["years"], today=d["today"])
        ds.series, ds.errors = d["series"], d["errors"]
        return ds


def format_exc() -> str:
    return traceback.format_exc(limit=2)
