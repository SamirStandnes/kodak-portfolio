"""Backfill historical closes and FX rates so the portfolio value curve covers
the whole life of the portfolio, not just the period since the daily price
cron started.

For every instrument with a Yahoo symbol, daily closes are downloaded for the
window in which it was held (first position transaction -> last one, or today
if still held) and written to `market_prices` with INSERT OR IGNORE, so
nothing the daily cron already stored is touched. FX pairs for every non-base
currency are backfilled into `exchange_rates` the same way.

Also compares each symbol's quote currency on Yahoo with the currency stored
in `instruments` and reports mismatches, since a wrong currency silently
mis-values a holding by the FX rate.

Usage:
    python -m kodak.maintenance.backfill_prices              # whole history
    python -m kodak.maintenance.backfill_prices --start 2024-01-01
    python -m kodak.maintenance.backfill_prices --dry-run    # report only

After running locally, push to the cloud with .\\workflows\\deploy_data.ps1.
"""
import argparse
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from kodak.shared.db import get_db_connection, query_df, execute_batch
from kodak.shared.utils import load_config, setup_logging
from kodak.shared.calculations import POSITION_TYPES

logger = logging.getLogger(__name__)
BASE_CURRENCY = load_config().get('base_currency', 'NOK')
PAD_DAYS = 7  # fetch slightly beyond the holding window so the first/last day has a close


def holding_windows() -> pd.DataFrame:
    """One row per instrument with a ticker-like symbol: id, symbol, currency, first, last, open."""
    placeholders = ','.join('?' * len(POSITION_TYPES))
    with get_db_connection() as conn:
        df = query_df(f"""
            SELECT i.id, i.symbol, i.currency,
                   MIN(t.date) AS first_date, MAX(t.date) AS last_date,
                   SUM(t.quantity) AS net_qty
            FROM transactions t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE i.symbol IS NOT NULL AND t.type IN ({placeholders})
            GROUP BY i.id, i.symbol, i.currency
        """, conn, params=tuple(POSITION_TYPES))
    if df.empty:
        return df
    df = df[~df['symbol'].str.contains(' ', regex=False)]  # broker display names can't be priced
    df['first_date'] = pd.to_datetime(df['first_date'].astype(str).str[:10])
    df['last_date'] = pd.to_datetime(df['last_date'].astype(str).str[:10])
    df['open'] = df['net_qty'].abs() > 0.001
    return df.reset_index(drop=True)


def download_closes(symbols: list, start: date, end: date) -> dict:
    """{symbol: Series(date -> close)} for every symbol Yahoo returned data for."""
    if not symbols:
        return {}
    logger.info(f"Downloading {len(symbols)} symbols from {start} to {end}...")
    raw = yf.download(symbols, start=start, end=end + timedelta(days=1), progress=False,
                      group_by='ticker', auto_adjust=False, threads=True)
    out = {}
    for sym in symbols:
        try:
            series = raw[sym]['Close'] if len(symbols) > 1 else raw['Close']
        except KeyError:
            continue
        series = series.dropna()
        series = series[series > 0]
        if not series.empty:
            out[sym] = series
    return out


def yahoo_currencies(symbols: list) -> dict:
    """{symbol: quote currency} via fast_info (one light request per symbol)."""
    result = {}
    for sym in symbols:
        try:
            result[sym] = yf.Ticker(sym).fast_info['currency']
        except Exception:
            result[sym] = None
    return result


def backfill(start: date | None, end: date, dry_run: bool) -> None:
    windows = holding_windows()
    if windows.empty:
        logger.warning("No priceable instruments found.")
        return

    global_start = start or windows['first_date'].min().date()
    symbols = windows['symbol'].tolist()
    closes = download_closes(symbols, global_start - timedelta(days=PAD_DAYS), end)

    # --- market_prices ---
    rows = []
    per_symbol = {}
    for _, w in windows.iterrows():
        series = closes.get(w['symbol'])
        if series is None:
            per_symbol[w['symbol']] = 0
            continue
        lo = max(w['first_date'].date(), global_start) - timedelta(days=PAD_DAYS)
        hi = (date.today() if w['open'] else w['last_date'].date() + timedelta(days=PAD_DAYS))
        hi = min(hi, end)
        sel = series[(series.index.date >= lo) & (series.index.date <= hi)]
        per_symbol[w['symbol']] = len(sel)
        rows.extend((int(w['id']), d.strftime('%Y-%m-%d'), float(v), w['currency'], 'yfinance-backfill')
                    for d, v in sel.items())

    missing = [s for s, n in per_symbol.items() if n == 0]
    logger.info(f"{len(rows)} daily closes for {len(per_symbol) - len(missing)} instruments; "
                f"no data for: {missing or 'none'}")

    # --- exchange_rates ---
    currencies = sorted(c for c in windows['currency'].dropna().unique() if c != BASE_CURRENCY)
    pairs = [f"{c}{BASE_CURRENCY}=X" for c in currencies]
    fx_closes = download_closes(pairs, global_start - timedelta(days=PAD_DAYS), end)
    fx_rows = []
    for c, pair in zip(currencies, pairs):
        series = fx_closes.get(pair)
        if series is None:
            logger.warning(f"No FX history for {pair}")
            continue
        fx_rows.extend((c, BASE_CURRENCY, d.strftime('%Y-%m-%d'), float(v)) for d, v in series.items())
    logger.info(f"{len(fx_rows)} daily FX rates for {currencies}")

    # --- currency sanity check ---
    yahoo_ccy = yahoo_currencies(symbols)
    mismatches = []
    for _, w in windows.iterrows():
        yc = yahoo_ccy.get(w['symbol'])
        if yc and yc.upper() != (w['currency'] or '').upper():
            mismatches.append((w['symbol'], w['currency'], yc, 'OPEN' if w['open'] else 'closed'))
    if mismatches:
        logger.warning("Currency in `instruments` differs from Yahoo's quote currency "
                       "(fix in data/reference/isin_map.csv, then re-run map_isins):")
        for sym, ours, theirs, state in mismatches:
            logger.warning(f"  {sym:<16} db={ours:<4} yahoo={theirs:<4} ({state})")

    if dry_run:
        logger.info("Dry run - nothing written.")
        return

    inserted = execute_batch(
        "INSERT OR IGNORE INTO market_prices (instrument_id, date, close, currency, source) VALUES (?, ?, ?, ?, ?)",
        rows)
    fx_inserted = execute_batch(
        "INSERT OR IGNORE INTO exchange_rates (from_currency, to_currency, date, rate) VALUES (?, ?, ?, ?)",
        fx_rows)
    logger.info(f"Inserted {inserted} new price rows and {fx_inserted} new FX rows "
                f"(existing rows left untouched).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--start', type=date.fromisoformat, default=None,
                        help='first date to backfill (default: first transaction)')
    parser.add_argument('--end', type=date.fromisoformat, default=date.today(),
                        help='last date to backfill (default: today)')
    parser.add_argument('--dry-run', action='store_true', help='download and report, write nothing')
    args = parser.parse_args()
    setup_logging('backfill_prices')
    backfill(args.start, args.end, args.dry_run)


if __name__ == '__main__':
    main()
