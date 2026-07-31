#!/usr/bin/env python3
"""
Daily Price Update Script for Heroku Scheduler

Fetches latest prices from Yahoo Finance and updates the PostgreSQL database.
Schedule this to run daily (e.g., 8 PM UTC after markets close).

Usage:
    heroku run python heroku/scripts/update_prices.py

Or via Heroku Scheduler:
    python heroku/scripts/update_prices.py
"""
import logging
import os
import sys
from datetime import datetime

import psycopg2
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """Get PostgreSQL connection from environment."""
    database_url = os.environ.get('DATABASE_URL', '')

    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)

    # Heroku provides postgres:// but psycopg2 needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(database_url)


def update_prices():
    """Fetches latest prices for all instruments and updates database."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all instruments with symbols
    cursor.execute("""
        SELECT DISTINCT i.id, i.symbol, i.currency
        FROM instruments i
        JOIN transactions t ON t.instrument_id = i.id
        WHERE i.symbol IS NOT NULL AND i.symbol != ''
    """)
    instruments = cursor.fetchall()

    if not instruments:
        # An empty result means the hosted database has no transactions, i.e. a
        # migration wiped it and never reloaded. Fail loudly - this used to log
        # one line and exit 0, so the nightly cron stayed green for days while
        # writing nothing.
        conn.close()
        raise RuntimeError(
            "No instruments to price: the hosted database has no transactions. "
            "Re-run workflows/deploy_data.ps1 to reload it from local SQLite."
        )

    # Build mapping
    symbols = [row[1] for row in instruments]
    id_map = {row[1]: {'id': row[0], 'currency': row[2]} for row in instruments}

    logger.info(f"Fetching prices for {len(symbols)} symbols: {symbols}")

    try:
        # Fetch prices from Yahoo Finance
        data = yf.download(symbols, period="5d", progress=False, auto_adjust=False)

        if data.empty:
            logger.warning("No data returned from Yahoo Finance")
            conn.close()
            return

        today = datetime.now().strftime('%Y-%m-%d')
        updated = 0
        errors = 0

        # Handle single vs multiple symbols
        if len(symbols) == 1:
            # Single symbol - data structure is different
            symbol = symbols[0]
            close_series = data['Close'].dropna()
            if not close_series.empty:
                price = float(close_series.iloc[-1])
                if price > 0:
                    meta = id_map[symbol]
                    try:
                        cursor.execute('''
                            INSERT INTO market_prices (instrument_id, date, close, currency, source)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (instrument_id, date) DO UPDATE SET
                                close = EXCLUDED.close,
                                currency = EXCLUDED.currency,
                                source = EXCLUDED.source
                        ''', (meta['id'], today, price, meta['currency'], 'yfinance'))
                        updated += 1
                        logger.info(f"  {symbol}: {price}")
                    except psycopg2.Error as e:
                        logger.error(f"  Error storing {symbol}: {e}")
                        errors += 1
        else:
            # Multiple symbols
            close_data = data['Close']

            for symbol in symbols:
                try:
                    if symbol not in close_data.columns:
                        logger.warning(f"  {symbol}: No data found")
                        continue

                    series = close_data[symbol].dropna()
                    if series.empty:
                        logger.warning(f"  {symbol}: Empty series")
                        continue

                    price = float(series.iloc[-1])
                    if price <= 0:
                        logger.warning(f"  {symbol}: Invalid price {price}")
                        continue

                    meta = id_map[symbol]
                    cursor.execute('''
                        INSERT INTO market_prices (instrument_id, date, close, currency, source)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (instrument_id, date) DO UPDATE SET
                            close = EXCLUDED.close,
                            currency = EXCLUDED.currency,
                            source = EXCLUDED.source
                    ''', (meta['id'], today, price, meta['currency'], 'yfinance'))
                    updated += 1
                    logger.info(f"  {symbol}: {price}")

                except Exception as e:
                    logger.error(f"  Error processing {symbol}: {e}")
                    errors += 1

        conn.commit()
        logger.info(f"Price update complete: {updated} updated, {errors} errors")

    except Exception as e:
        logger.error(f"Error fetching data from Yahoo Finance: {e}")
        conn.rollback()

    finally:
        conn.close()


def update_exchange_rates():
    """Updates common exchange rates."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get base currency from environment or default to NOK
    base_currency = os.environ.get('BASE_CURRENCY', 'NOK')

    # Get distinct currencies used in transactions (excluding base currency)
    cursor.execute("""
        SELECT DISTINCT currency
        FROM transactions
        WHERE currency != %s AND currency IS NOT NULL
    """, (base_currency,))
    currencies = [row[0] for row in cursor.fetchall()]

    if not currencies:
        logger.info("No foreign currencies to update")
        conn.close()
        return

    logger.info(f"Updating exchange rates for: {currencies} -> {base_currency}")

    today = datetime.now().strftime('%Y-%m-%d')
    updated = 0

    for currency in currencies:
        try:
            pair = f"{currency}{base_currency}=X"
            ticker = yf.Ticker(pair)
            info = ticker.info

            rate = info.get('regularMarketPrice') or info.get('previousClose')

            if rate and rate > 0:
                cursor.execute('''
                    INSERT INTO exchange_rates (from_currency, to_currency, date, rate)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (from_currency, to_currency, date) DO UPDATE SET
                        rate = EXCLUDED.rate
                ''', (currency, base_currency, today, rate))
                updated += 1
                logger.info(f"  {currency}/{base_currency}: {rate}")
            else:
                logger.warning(f"  {currency}/{base_currency}: No rate found")

        except Exception as e:
            logger.error(f"  Error fetching {currency}/{base_currency}: {e}")

    conn.commit()
    conn.close()
    logger.info(f"Exchange rate update complete: {updated} updated")


def main():
    logger.info("=" * 50)
    logger.info("Starting daily price update")
    logger.info("=" * 50)

    update_prices()
    update_exchange_rates()

    logger.info("=" * 50)
    logger.info("Daily update complete")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
