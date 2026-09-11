import logging
import os
import sqlite3

import pandas as pd

from kodak.shared.utils import load_config

logger = logging.getLogger(__name__)

# Adjust path relative to this script
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'database', 'portfolio.db')

def initialize_database():
    """
    Initializes the SQLite database and reference files.
    """
    config = load_config()
    base_curr = config.get('base_currency', 'NOK')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # --- 1. Master Data ---

    # Accounts: The containers for assets
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            broker TEXT,
            currency TEXT NOT NULL DEFAULT '{base_curr}', -- Reporting currency
            type TEXT,
            external_id TEXT UNIQUE -- The ID from the import file (e.g. 19269921)
        )
    ''')

    # Instruments: The tradable assets
    c.execute('''
        CREATE TABLE IF NOT EXISTS instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # --- 2. The Ledger ---

    # Transactions: The events
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT UNIQUE, -- GlobalID from old DB
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            instrument_id INTEGER REFERENCES instruments(id),
            
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            
            quantity REAL,
            price REAL,
            
            amount REAL,           -- In transaction currency (Currency_Raw)
            currency TEXT NOT NULL,
            
            exchange_rate REAL,    -- To convert to Account Currency
            amount_local REAL,     -- In Account Currency (Amount_NOK)
            
            fee REAL,
            fee_currency TEXT,
            fee_local REAL,        -- Fee converted to Account Currency
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT,
            batch_id TEXT,
            source_file TEXT,
            hash TEXT,

            -- Broker-side record of truth (populated when the export provides it):
            broker_id TEXT,          -- the broker's own transaction id (Nordnet "Id")
            balance_after REAL,      -- broker cash balance after this row ("Saldo")
            balance_currency TEXT    -- currency that balance_after is stated in
        )
    ''')

    # Older databases predate the broker_* columns: add them in place.
    existing = {row[1] for row in c.execute("PRAGMA table_info(transactions)")}
    for col, ddl in (('broker_id', 'TEXT'), ('balance_after', 'REAL'), ('balance_currency', 'TEXT')):
        if col not in existing:
            c.execute(f"ALTER TABLE transactions ADD COLUMN {col} {ddl}")
            logger.info(f"Added transactions.{col}")

    # --- 3. Market Data ---

    c.execute('''
        CREATE TABLE IF NOT EXISTS market_prices (
            instrument_id INTEGER NOT NULL REFERENCES instruments(id),
            date TEXT NOT NULL,
            close REAL,
            currency TEXT,
            source TEXT,
            PRIMARY KEY (instrument_id, date)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS exchange_rates (
            from_currency TEXT NOT NULL,
            to_currency TEXT NOT NULL,
            date TEXT NOT NULL,
            rate REAL,
            PRIMARY KEY (from_currency, to_currency, date)
        )
    ''')

    conn.commit()
    conn.close()
    logger.info(f"Database schema ensured at {DB_PATH}")

    # --- 4. Reference Templates ---
    ref_dir = os.path.join('data', 'reference')
    os.makedirs(ref_dir, exist_ok=True)

    # ISIN Map Template
    isin_path = os.path.join(ref_dir, 'isin_map.csv')
    if not os.path.exists(isin_path):
        df_isin = pd.DataFrame(columns=['isin', 'symbol', 'currency', 'sector', 'region', 'country', 'asset_class'])
        df_isin.to_csv(isin_path, index=False)
        logger.info(f"Created template: {isin_path}")

    # Accounts Map Template
    acc_path = os.path.join(ref_dir, 'accounts_map.csv')
    if not os.path.exists(acc_path):
        df_acc = pd.DataFrame(columns=['external_id', 'name', 'broker', 'currency'])
        df_acc.to_csv(acc_path, index=False)
        logger.info(f"Created template: {acc_path}")

if __name__ == '__main__':
    initialize_database()
