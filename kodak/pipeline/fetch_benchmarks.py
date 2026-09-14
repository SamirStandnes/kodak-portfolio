"""Fetch daily closes for the configured benchmark indices into
``benchmark_prices`` (local SQLite). Idempotent: existing rows are left alone.

Usage:
    python -m kodak.pipeline.fetch_benchmarks            # since last stored date
    python -m kodak.pipeline.fetch_benchmarks --full     # whole history again

Runs as part of refresh_market_data.ps1 / add_transactions.ps1. The cloud
cron (heroku/scripts/update_prices.py) does the same against Postgres.
"""
import argparse
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from kodak.shared.db import get_db_connection, execute_batch, execute_scalar
from kodak.shared.utils import setup_logging
from kodak.shared.benchmarks import configured_benchmarks, ensure_tables, sync_dimension, latest_benchmark_dates

logger = logging.getLogger(__name__)
PAD_DAYS = 7


def default_start() -> date:
    first = execute_scalar("SELECT MIN(date) FROM transactions")
    return date.fromisoformat(str(first)[:10]) if first else date.today() - timedelta(days=365 * 5)


def download(symbol: str, start: date, end: date) -> pd.Series:
    raw = yf.download(symbol, start=start, end=end + timedelta(days=1), progress=False, auto_adjust=False)
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    close = raw['Close']
    if isinstance(close, pd.DataFrame):          # yfinance returns a 1-col frame for single symbols
        close = close.iloc[:, 0]
    close = close.dropna()
    return close[close > 0]


def fetch(full: bool = False) -> int:
    with get_db_connection() as conn:
        ensure_tables(conn)
        sync_dimension(conn)
    latest = latest_benchmark_dates()
    end = date.today()
    total = 0
    for b in configured_benchmarks():
        start = default_start()
        if not full and b.code in latest:
            start = max(start, date.fromisoformat(latest[b.code][:10]) - timedelta(days=PAD_DAYS))
        series = download(b.symbol, start - timedelta(days=PAD_DAYS), end)
        if series.empty:
            logger.warning(f"{b.code} ({b.symbol}): no data from Yahoo")
            continue
        rows = [(b.code, d.strftime('%Y-%m-%d'), float(v)) for d, v in series.items()]
        n = execute_batch("INSERT OR IGNORE INTO benchmark_prices (code, date, close) VALUES (?, ?, ?)", rows)
        total += n
        logger.info(f"{b.code} ({b.symbol}): {len(rows)} closes fetched, {n} new, latest {series.index[-1].date()}")
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--full', action='store_true', help='re-fetch the whole history')
    args = parser.parse_args()
    setup_logging('fetch_benchmarks')
    fetch(full=args.full)


if __name__ == '__main__':
    main()
