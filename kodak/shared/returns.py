"""Return mathematics: time-weighted returns and index shadow portfolios.

Pure pandas, no database and no network, so every function here is unit
testable with a handful of rows. Conventions:

- ``values`` is the portfolio value per date (base currency), ``flows`` the
  net external cash flow on the same dates (deposits positive, withdrawals
  negative). A flow is assumed to arrive at the start of its day, i.e. it is
  part of that day's closing value but earned no return that day.
- XIRR-style cash-flow lists follow ``calculations.xirr``: money the investor
  pays in is negative, money coming back (or the final value) positive.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from kodak.shared.calculations import xirr


def growth_index(values: pd.Series, flows: pd.Series) -> pd.Series:
    """Chain-linked growth of 1.0 invested at the first date with capital.

    Daily return r_t = (V_t - F_t) / V_{t-1} - 1. Days where the previous
    value is not positive (before the first deposit, or a fully withdrawn
    portfolio) contribute no return; the chain simply continues.
    """
    values = values.astype(float)
    flows = flows.reindex(values.index).fillna(0.0).astype(float)
    prev = values.shift(1)
    daily = pd.Series(0.0, index=values.index)
    ok = prev > 0
    daily[ok] = (values[ok] - flows[ok]) / prev[ok] - 1.0
    return (1.0 + daily).cumprod()


def annualized(growth: float, days: float) -> Optional[float]:
    """Annualized rate from total growth over ``days`` calendar days."""
    if days <= 0 or growth <= 0:
        return None
    return growth ** (365.25 / days) - 1.0


def yearly_returns(index: pd.Series) -> pd.Series:
    """Calendar-year returns from a growth index (year -> return as a fraction).

    The first year runs from the first observation; every other year from
    the previous year's last observation."""
    if index.empty:
        return pd.Series(dtype=float)
    year_end = index.groupby(index.index.year).last()
    prev = year_end.shift(1)
    prev.iloc[0] = index.iloc[0]
    return year_end / prev - 1.0


def rebase(series: pd.Series, dates: pd.DatetimeIndex, base: float = 1.0) -> pd.Series:
    """Align a price series to ``dates`` (carrying the last close forward) and
    scale it so it equals ``base`` on the first date."""
    aligned = series.sort_index().reindex(series.index.union(dates)).ffill().reindex(dates)
    first = aligned.dropna()
    if first.empty or first.iloc[0] == 0:
        return pd.Series(np.nan, index=dates)
    return aligned / first.iloc[0] * base


@dataclass
class ShadowResult:
    values: pd.Series          # shadow portfolio value per date
    final_value: float
    xirr_pct: Optional[float]  # money-weighted return of the same flows in the index


def shadow_portfolio(flows: pd.Series, prices: pd.Series) -> ShadowResult:
    """Put every external cash flow into the benchmark on the day it happened.

    Deposits buy units at that day's price, withdrawals sell them. The result
    is what the same money would be worth had it tracked the benchmark, and
    the XIRR of those flows against that final value - directly comparable
    with the portfolio's own XIRR because the cash flows are identical.
    """
    prices = prices.sort_index().reindex(prices.index.union(flows.index)).ffill().bfill().reindex(flows.index)
    units = (flows / prices).fillna(0.0).cumsum()
    values = units * prices
    final_value = float(values.iloc[-1]) if not values.empty else 0.0
    cash_flows = [(pd.Timestamp(d), -float(f)) for d, f in flows.items() if abs(f) > 0.005]
    if final_value > 0:
        cash_flows.append((pd.Timestamp(flows.index[-1]), final_value))
    rate = xirr(cash_flows) * 100 if len(cash_flows) > 1 else None
    return ShadowResult(values=values, final_value=final_value, xirr_pct=rate)
