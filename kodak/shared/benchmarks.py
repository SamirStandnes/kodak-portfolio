"""Benchmark indices: storage, retrieval and comparison with the portfolio.

Layers (keep them separate):

- **Config**: which benchmarks exist lives in ``config.yaml`` (``benchmarks:``)
  and is mirrored into the ``benchmarks`` table so the cloud (which has no
  yaml) and the audit can read it.
- **Storage**: ``benchmarks`` (dimension) and ``benchmark_prices`` (daily
  closes in the benchmark's own currency). Deliberately separate from
  ``instruments`` / ``market_prices``: an index is not something you hold.
- **Retrieval**: ``benchmark_series_local`` gives a close series converted to
  the base currency with the stored FX rates, which is the only form the
  comparison ever needs.
- **Comparison**: ``compare_to_benchmarks`` combines the portfolio's value
  history with the benchmark series using the pure functions in
  ``kodak.shared.returns``. No network anywhere in this module.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from kodak.shared.db import get_db_connection, query_df
from kodak.shared.utils import load_config
from kodak.shared.market_data import get_exchange_rate
from kodak.shared import returns as R

_cfg = load_config()
BASE_CURRENCY = _cfg.get('base_currency', 'NOK')

DDL = [
    """CREATE TABLE IF NOT EXISTS benchmarks (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        currency TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS benchmark_prices (
        code TEXT NOT NULL REFERENCES benchmarks(code),
        date TEXT NOT NULL,
        close DOUBLE PRECISION,
        PRIMARY KEY (code, date)
    )""",
]


@dataclass(frozen=True)
class Benchmark:
    code: str
    name: str
    symbol: str
    currency: str
    sort_order: int = 0


def configured_benchmarks() -> List[Benchmark]:
    """Benchmarks from config.yaml (or the cloud config adapter)."""
    out = []
    for i, b in enumerate(_cfg.get('benchmarks', []) or []):
        out.append(Benchmark(code=str(b['code']), name=str(b.get('name', b['code'])),
                             symbol=str(b['symbol']), currency=str(b.get('currency', BASE_CURRENCY)).upper(),
                             sort_order=int(b.get('sort_order', i))))
    return out


def ensure_tables(conn) -> None:
    """Create the two benchmark tables if missing (SQLite and Postgres)."""
    for ddl in DDL:
        conn.execute(ddl)
    conn.commit()


def sync_dimension(conn, benchmarks: Optional[List[Benchmark]] = None) -> None:
    """Upsert the configured benchmarks into the ``benchmarks`` table."""
    benchmarks = benchmarks if benchmarks is not None else configured_benchmarks()
    for b in benchmarks:
        row = conn.execute("SELECT 1 FROM benchmarks WHERE code = ?", (b.code,)).fetchone()
        if row:
            conn.execute("UPDATE benchmarks SET name = ?, symbol = ?, currency = ?, sort_order = ? WHERE code = ?",
                         (b.name, b.symbol, b.currency, b.sort_order, b.code))
        else:
            conn.execute("INSERT INTO benchmarks (code, name, symbol, currency, sort_order) VALUES (?, ?, ?, ?, ?)",
                         (b.code, b.name, b.symbol, b.currency, b.sort_order))
    conn.commit()


def stored_benchmarks() -> List[Benchmark]:
    """Benchmarks as recorded in the database (what the cloud cron uses)."""
    with get_db_connection() as conn:
        try:
            df = query_df("SELECT code, name, symbol, currency, sort_order FROM benchmarks ORDER BY sort_order", conn)
        except Exception:
            return []
    return [Benchmark(r.code, r.name, r.symbol, r.currency, int(r.sort_order or 0)) for r in df.itertuples()]


def benchmark_prices(code: str) -> pd.Series:
    """Stored closes for one benchmark in its own currency (date -> close)."""
    with get_db_connection() as conn:
        try:
            df = query_df("SELECT date, close FROM benchmark_prices WHERE code = ? ORDER BY date",
                          conn, params=(code,))
        except Exception:
            return pd.Series(dtype=float)
    if df.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(df['date'].astype(str).str[:10], format='%Y-%m-%d')
    return pd.Series(df['close'].astype(float).values, index=idx).dropna()


def _fx_series(currency: str, dates: pd.DatetimeIndex) -> pd.Series:
    if currency == BASE_CURRENCY:
        return pd.Series(1.0, index=dates)
    with get_db_connection() as conn:
        df = query_df("SELECT date, rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ? ORDER BY date",
                      conn, params=(currency, BASE_CURRENCY))
    if df.empty:
        return pd.Series(get_exchange_rate(currency, BASE_CURRENCY), index=dates)
    idx = pd.to_datetime(df['date'].astype(str).str[:10], format='%Y-%m-%d')
    s = pd.Series(df['rate'].astype(float).values, index=idx)
    return s.reindex(s.index.union(dates)).ffill().bfill().reindex(dates)


def benchmark_series_local(bench: Benchmark, dates: Optional[pd.DatetimeIndex] = None) -> pd.Series:
    """Closes converted to the base currency; aligned to ``dates`` if given."""
    px = benchmark_prices(bench.code)
    if px.empty:
        return px
    idx = dates if dates is not None else px.index
    px = px.reindex(px.index.union(idx)).ffill().reindex(idx) if dates is not None else px
    return px * _fx_series(bench.currency, px.index)


def latest_benchmark_dates() -> Dict[str, str]:
    with get_db_connection() as conn:
        try:
            df = query_df("SELECT code, MAX(date) AS latest FROM benchmark_prices GROUP BY code", conn)
        except Exception:
            return {}
    return dict(zip(df['code'], df['latest'].astype(str)))


@dataclass
class BenchmarkComparison:
    growth: pd.DataFrame            # date x ['Portfolio', <name>...], growth of 100
    yearly: pd.DataFrame            # year x ['Portfolio TWR', <name>...] in percent
    annualized: Dict[str, float]    # name -> annualized TWR in percent
    shadow: pd.DataFrame            # per benchmark: same flows invested in the index
    start: pd.Timestamp
    end: pd.Timestamp
    missing: List[str] = field(default_factory=list)   # benchmarks without stored prices


def compare_to_benchmarks(history: pd.DataFrame, portfolio_xirr_pct: Optional[float] = None,
                          benchmarks: Optional[List[Benchmark]] = None) -> Optional[BenchmarkComparison]:
    """Time-weighted comparison plus the "same deposits in the index" view.

    ``history`` is ``get_portfolio_value_history()`` output (date, total_value,
    net_deposits ...). Returns None when there is nothing to compare.
    """
    if history is None or len(history) < 2:
        return None
    h = history.set_index(pd.DatetimeIndex(history['date'])).sort_index()
    values = h['total_value'].astype(float)
    flows = h['net_deposits'].astype(float).diff()
    flows.iloc[0] = float(h['net_deposits'].iloc[0])

    # Start the clock at the first day with capital in the portfolio.
    funded = values[values > 0]
    if funded.empty:
        return None
    start = funded.index[0]
    values, flows = values[start:], flows[start:]
    dates = values.index

    growth = pd.DataFrame(index=dates)
    growth['Portfolio'] = R.growth_index(values, flows) * 100.0
    yearly = pd.DataFrame({'Portfolio TWR': R.yearly_returns(growth['Portfolio']) * 100.0})
    days = (dates[-1] - dates[0]).days
    ann = {'Portfolio': (R.annualized(growth['Portfolio'].iloc[-1] / 100.0, days) or 0.0) * 100.0}

    shadow_rows, missing = [], []
    for b in (benchmarks if benchmarks is not None else configured_benchmarks()):
        series = benchmark_series_local(b, dates)
        if series.dropna().empty:
            missing.append(b.name)
            continue
        growth[b.name] = R.rebase(series, dates, 100.0)
        yearly[b.name] = R.yearly_returns(growth[b.name]) * 100.0
        ann[b.name] = (R.annualized(growth[b.name].iloc[-1] / 100.0, days) or 0.0) * 100.0
        sh = R.shadow_portfolio(flows, series)
        shadow_rows.append({
            'benchmark': b.name,
            'index_value': sh.final_value,
            'portfolio_value': float(values.iloc[-1]),
            'difference': float(values.iloc[-1]) - sh.final_value,
            'index_xirr_pct': sh.xirr_pct,
            'portfolio_xirr_pct': portfolio_xirr_pct,
        })

    yearly.index = yearly.index.astype(str)
    return BenchmarkComparison(growth=growth, yearly=yearly, annualized=ann,
                               shadow=pd.DataFrame(shadow_rows), start=dates[0], end=dates[-1],
                               missing=missing)
