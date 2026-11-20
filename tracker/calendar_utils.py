"""US business-day helpers and month-end / quarter-end repo windows."""
from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def month_end_window_dates(start: pd.Timestamp, end: pd.Timestamp, after: int = 2) -> set[pd.Timestamp]:
    """Last business day of each month plus the first `after` business days of the next month.

    Repo rates and SRF usage routinely spike around month/quarter ends; breaches inside this
    window are flagged but never alerted unless they persist beyond it.
    """
    out: set[pd.Timestamp] = set()
    months = pd.period_range(start - pd.offsets.MonthBegin(1), end + pd.offsets.MonthEnd(1), freq="M")
    for p in months:
        last_bd = BDAY.rollback(p.end_time.normalize())
        out.add(pd.Timestamp(last_bd))
        d = pd.Timestamp(last_bd)
        for _ in range(after):
            d = d + BDAY
            out.add(pd.Timestamp(d))
    return out


def in_month_end_window(index: pd.DatetimeIndex, after: int = 2) -> pd.Series:
    if len(index) == 0:
        return pd.Series([], dtype=bool, index=index)
    win = month_end_window_dates(index.min(), index.max(), after)
    return pd.Series([pd.Timestamp(d).normalize() in win for d in index], index=index)
