#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

Replaces the hosted database (Neon Postgres) with the contents of the local
SQLite database, which is the source of truth for transactions.

The whole migration - schema drop/create plus every row - runs inside ONE
transaction. Readers (the Streamlit dashboard) keep seeing the previous data
until the commit lands, so the dashboard is never half-empty mid-run. Rows are
sent in batches via execute_values instead of one round trip per row.

Any failure rolls back and exits non-zero. A partially loaded database is never
left behind, and the pipeline can trust the exit code.

Usage:
    python -m heroku.scripts.migrate_db --sqlite database/portfolio.db --pg-url $DATABASE_URL

Or with environment variable:
    export DATABASE_URL=postgresql://...
    python -m heroku.scripts.migrate_db --sqlite database/portfolio.db
"""
import argparse
import logging
import os
import sqlite3
import sys
import time

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Table load order matters: foreign keys point backwards in this list.
# (name, columns, has_serial_id)
TABLES = [
    ('accounts',
     ['name', 'broker', 'currency', 'type', 'external_id'],
     True),
    ('instruments',
     ['isin', 'symbol', 'name', 'type', 'currency', 'exchange_mic', 'sector',
      'region', 'country', 'asset_class'],
     True),
    ('transactions',
     ['external_id', 'account_id', 'instrument_id', 'date', 'type', 'quantity',
      'price', 'amount', 'currency', 'exchange_rate', 'amount_local', 'fee',
      'fee_currency', 'fee_local', 'created_at', 'notes', 'batch_id',
      'source_file', 'hash'],
     True),
    ('market_prices',
     ['instrument_id', 'date', 'close', 'currency', 'source'],
     False),
    ('exchange_rates',
     ['from_currency', 'to_currency', 'date', 'rate'],
     False),
]

# Fail fast instead of queueing behind a long-running dashboard query. DROP TABLE
# needs an ACCESS EXCLUSIVE lock, so without this the migration can hang for
# minutes with no output.
LOCK_TIMEOUT = '60s'
DEFAULT_BATCH_SIZE = 500


def create_postgresql_schema(pg_conn, base_currency='NOK'):
    """Drops and recreates the schema. Caller owns the transaction."""
    cursor = pg_conn.cursor()

    logger.info("Dropping existing tables if they exist...")
    cursor.execute("DROP TABLE IF EXISTS exchange_rates CASCADE")
    cursor.execute("DROP TABLE IF EXISTS market_prices CASCADE")
    cursor.execute("DROP TABLE IF EXISTS transactions CASCADE")
    cursor.execute("DROP TABLE IF EXISTS instruments CASCADE")
    cursor.execute("DROP TABLE IF EXISTS accounts CASCADE")

    logger.info("Creating tables...")
    cursor.execute(f'''
        CREATE TABLE accounts (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            broker TEXT,
            currency TEXT NOT NULL DEFAULT '{base_currency}',
            type TEXT,
            external_id TEXT UNIQUE
        )
    ''')

    cursor.execute('''
        CREATE TABLE instruments (
            id SERIAL PRIMARY KEY,
            isin TEXT UNIQUE,
            symbol TEXT,
            name TEXT,
            type TEXT,
            currency TEXT,
            exchange_mic TEXT,
            sector TEXT,
            region TEXT,
            country TEXT,
            asset_class TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE transactions (
            id SERIAL PRIMARY KEY,
            external_id TEXT UNIQUE,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            instrument_id INTEGER REFERENCES instruments(id),
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            quantity DOUBLE PRECISION,
            price DOUBLE PRECISION,
            amount DOUBLE PRECISION,
            currency TEXT NOT NULL,
            exchange_rate DOUBLE PRECISION,
            amount_local DOUBLE PRECISION,
            fee DOUBLE PRECISION,
            fee_currency TEXT,
            fee_local DOUBLE PRECISION,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            batch_id TEXT,
            source_file TEXT,
            hash TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE market_prices (
            instrument_id INTEGER NOT NULL REFERENCES instruments(id),
            date TEXT NOT NULL,
            close DOUBLE PRECISION,
            currency TEXT,
            source TEXT,
            PRIMARY KEY (instrument_id, date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE exchange_rates (
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            date TEXT NOT NULL,
            rate DOUBLE PRECISION,
            PRIMARY KEY (from_currency, to_currency, date)
        )
    ''')

    logger.info("Schema created")


def migrate_table(sqlite_conn, pg_conn, table_name, columns, has_serial_id,
                  batch_size=DEFAULT_BATCH_SIZE):
    """Copies one table SQLite -> PostgreSQL in batches.

    Raises on any error: a row that will not insert means the hosted database
    would silently differ from local, so the whole migration must roll back.
    """
    all_columns = ['id'] + columns if has_serial_id else list(columns)

    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute(f"SELECT {','.join(all_columns)} FROM {table_name}")
    rows = [tuple(row) for row in sqlite_cursor.fetchall()]

    pg_cursor = pg_conn.cursor()

    if not rows:
        logger.info(f"  {table_name}: no rows in SQLite - leaving empty")
    else:
        insert_sql = (
            f"INSERT INTO {table_name} ({','.join(all_columns)}) VALUES %s"
        )
        started = time.perf_counter()
        execute_values(pg_cursor, insert_sql, rows, page_size=batch_size)
        elapsed = time.perf_counter() - started
        logger.info(f"  {table_name}: inserted {len(rows)} rows in {elapsed:.1f}s")

    if has_serial_id:
        # Rows carry explicit ids to preserve foreign keys, so the sequence has
        # to be moved past them or the next INSERT collides.
        pg_cursor.execute(f"""
            SELECT setval(pg_get_serial_sequence('{table_name}', 'id'),
                         COALESCE((SELECT MAX(id) FROM {table_name}), 1))
        """)

    # Verify inside the transaction, before anything is visible to readers.
    pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    pg_count = pg_cursor.fetchone()[0]
    if pg_count != len(rows):
        raise RuntimeError(
            f"{table_name}: row count mismatch after load "
            f"(SQLite {len(rows)}, PostgreSQL {pg_count})"
        )

    return len(rows)


def migrate(sqlite_path: str, pg_url: str, base_currency: str = 'NOK',
            batch_size: int = DEFAULT_BATCH_SIZE):
    """Replaces the hosted database with local SQLite data, atomically."""
    logger.info(f"Starting migration from {sqlite_path}")

    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite database not found: {sqlite_path}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(sqlite_path)

    # Heroku/Neon may hand out postgres://, psycopg2 wants postgresql://
    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql://", 1)

    try:
        pg_conn = psycopg2.connect(pg_url, connect_timeout=30)
    except psycopg2.Error as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
        sqlite_conn.close()
        sys.exit(1)

    pg_conn.autocommit = False
    started = time.perf_counter()
    total_rows = 0

    try:
        # SET after connect, not as a startup parameter: Neon's pooled endpoint
        # rejects options in the startup packet.
        pg_conn.cursor().execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

        create_postgresql_schema(pg_conn, base_currency)

        for table_name, columns, has_serial_id in TABLES:
            total_rows += migrate_table(
                sqlite_conn, pg_conn, table_name, columns, has_serial_id,
                batch_size
            )

        pg_conn.commit()
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"Migration failed, rolled back - hosted database unchanged: {e}")
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_conn.close()

    elapsed = time.perf_counter() - started
    logger.info(f"Migration complete: {total_rows} rows in {elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(description='Migrate SQLite database to PostgreSQL')
    parser.add_argument('--sqlite', required=True, help='Path to SQLite database file')
    parser.add_argument('--pg-url', help='PostgreSQL connection URL (or use DATABASE_URL env var)')
    parser.add_argument('--base-currency', default='NOK', help='Base currency (default: NOK)')
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                        help=f'Rows per INSERT batch (default: {DEFAULT_BATCH_SIZE})')

    args = parser.parse_args()

    pg_url = args.pg_url or os.environ.get('DATABASE_URL')
    if not pg_url:
        logger.error("PostgreSQL URL not provided. Use --pg-url or set DATABASE_URL environment variable")
        sys.exit(1)

    migrate(args.sqlite, pg_url, args.base_currency, args.batch_size)


if __name__ == '__main__':
    main()
