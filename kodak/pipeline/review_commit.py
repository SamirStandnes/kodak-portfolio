import logging
import os
import pandas as pd
from kodak.shared.db import get_connection, execute_non_query, execute_scalar, execute_query, create_backup
from kodak.shared.utils import load_config

logger = logging.getLogger(__name__)

ACCOUNTS_MAP_PATH = os.path.join('data', 'reference', 'accounts_map.csv')
ISIN_MAP_PATH = os.path.join('data', 'reference', 'isin_map.csv')


def _append_placeholder_accounts(unknown_accs):
    """Append placeholder rows to accounts_map.csv for new accounts."""
    if not os.path.exists(ACCOUNTS_MAP_PATH):
        logger.warning(f"Accounts map not found at {ACCOUNTS_MAP_PATH}")
        return

    try:
        existing_df = pd.read_csv(ACCOUNTS_MAP_PATH)
        existing_ids = set(existing_df['external_id'].astype(str))

        new_rows = []
        for acc_ext in unknown_accs:
            if str(acc_ext) not in existing_ids:
                new_rows.append({
                    'external_id': acc_ext,
                    'name': f'New Account {acc_ext}',
                    'broker': 'UNKNOWN',
                    'type': 'UNKNOWN'
                })

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined.to_csv(ACCOUNTS_MAP_PATH, index=False)
            print(f"[+] Added {len(new_rows)} placeholder(s) to accounts_map.csv - please edit UNKNOWN values.")
    except Exception as e:
        logger.warning(f"Could not update accounts_map.csv: {e}")


def _append_placeholder_instruments(df, unknown_isins):
    """Append placeholder rows to isin_map.csv for new instruments."""
    if not os.path.exists(ISIN_MAP_PATH):
        logger.warning(f"ISIN map not found at {ISIN_MAP_PATH}")
        return

    try:
        existing_df = pd.read_csv(ISIN_MAP_PATH)
        existing_isins = set(existing_df['isin'].astype(str))

        # Get symbol and currency from the staged data for each new ISIN
        staged_instruments = df[df['isin'].isin(unknown_isins)][['isin', 'symbol', 'currency']].drop_duplicates('isin')

        new_rows = []
        for _, row in staged_instruments.iterrows():
            if str(row['isin']) not in existing_isins:
                new_rows.append({
                    'isin': row['isin'],
                    'symbol': row['symbol'] or 'UNKNOWN',
                    'currency': row['currency'] or 'UNKNOWN',
                    'sector': '',
                    'region': 'Unknown',
                    'country': '',
                    'asset_class': 'Equity'
                })

        if new_rows:
            new_df = pd.DataFrame(new_rows)
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined.to_csv(ISIN_MAP_PATH, index=False)
            for r in new_rows:
                print(f"  [+] Added {r['isin']} ({r['symbol']}) to isin_map.csv - please update symbol/metadata.")
    except Exception as e:
        logger.warning(f"Could not update isin_map.csv: {e}")


def review_and_commit():
    conn = get_connection()
    config = load_config()
    base_curr = config.get('base_currency', 'NOK')
    
    # Check Staging
    try:
        df = pd.read_sql("SELECT * FROM transactions_staging", conn)
    except Exception as e:
        logger.info(f"Staging table does not exist or is empty: {e}")
        print("Staging table does not exist or is empty.")
        conn.close()
        return

    if df.empty:
        print("No transactions in staging.")
        conn.close()
        return

    print(f"\n--- REVIEW STAGING ({len(df)} transactions) ---")

    # Sort by date and show more useful columns
    display_df = df.sort_values('date').copy()
    display_cols = ['date', 'type', 'symbol', 'quantity', 'price', 'amount_local', 'fee_local']
    display_cols = [c for c in display_cols if c in display_df.columns]

    # Format numeric columns for readability
    pd.set_option('display.float_format', lambda x: f'{x:,.2f}' if abs(x) >= 0.01 else f'{x:.4f}')
    print(display_df[display_cols].head(15).to_string(index=False))
    if len(df) > 15:
        print(f"... and {len(df)-15} more.")

    # Check for New Accounts/Instruments
    staged_accs = df['account_external_id'].unique()
    staged_isins = df['isin'].unique()
    
    # Find unknown accounts
    unknown_accs = []
    for acc in staged_accs:
        exists = execute_scalar("SELECT 1 FROM accounts WHERE external_id = ?", (acc,))
        if not exists:
            unknown_accs.append(acc)
            
    # Find unknown instruments
    unknown_insts = []
    for isin in staged_isins:
        if not isin: continue
        exists = execute_scalar("SELECT 1 FROM instruments WHERE isin = ?", (isin,))
        if not exists:
            unknown_insts.append(isin)

    if unknown_accs:
        print(f"\n[!] WARNING: {len(unknown_accs)} New Accounts detected:")
        print(unknown_accs)
        print("They will be auto-created with default settings.")
        _append_placeholder_accounts(unknown_accs)

    if unknown_insts:
        print(f"\n[!] NOTICE: {len(unknown_insts)} New Instruments detected.")
        _append_placeholder_instruments(df, unknown_insts)

    choice = input("\nCommit these transactions? (y/n/clear): ").lower().strip()
    
    if choice == 'clear':
        execute_non_query("DELETE FROM transactions_staging")
        print("Staging cleared.")
    elif choice == 'y':
        create_backup("before_commit")
        _commit_data(df, unknown_accs, unknown_insts, base_curr)
    else:
        print("Operation cancelled.")
    
    conn.close()

def _commit_data(df, new_accs, new_isins, base_curr):
    print("Committing...")
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Create New Accounts
        for acc_ext in new_accs:
            # Try to infer broker from ID or source file (simplified here)
            name = f"New Account {acc_ext}"
            cursor.execute("INSERT INTO accounts (name, external_id, currency) VALUES (?, ?, ?)", (name, acc_ext, base_curr))
            print(f"Created account: {name} ({base_curr})")

        # 2. Create New Instruments
        # We need symbol from the dataframe for these ISINs
        unique_instruments = df[df['isin'].isin(new_isins)][['isin', 'symbol']].drop_duplicates('isin')
        for _, row in unique_instruments.iterrows():
            cursor.execute("INSERT INTO instruments (isin, symbol) VALUES (?, ?)", (row['isin'], row['symbol']))
            # print(f"Created instrument: {row['symbol']} ({row['isin']})")

        # 3. Insert Transactions
        # Prepare cache for lookups using the SAME cursor/connection to see uncommitted changes
        cursor.execute("SELECT external_id, id FROM accounts")
        acc_map = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor.execute("SELECT isin, id FROM instruments")
        inst_map = {row[0]: row[1] for row in cursor.fetchall()}
        
        count = 0
        for _, row in df.iterrows():
            acc_id = acc_map.get(row['account_external_id'])
            inst_id = inst_map.get(row['isin'])
            
            # Skip if account missing (should not happen if logic above is correct)
            if acc_id is None:
                print(f"Error: Account {row['account_external_id']} not found in map.")
                continue
            
            cursor.execute('''
                INSERT INTO transactions (
                    external_id, account_id, instrument_id, date, type,
                    quantity, price, amount, currency,
                    amount_local, exchange_rate, fee, fee_currency, fee_local, notes, batch_id, source_file, hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                row['external_id'], acc_id, inst_id, row['date'], row['type'],
                row['quantity'], row['price'], row['amount'], row['currency'],
                row['amount_local'], row['exchange_rate'], row['fee'], row.get('fee_currency'), row.get('fee_local'), row['description'], row.get('batch_id'), row.get('source_file'), row.get('hash')
            ))
            count += 1
            
        # 4. Clear Staging
        cursor.execute("DELETE FROM transactions_staging")
        
        conn.commit()
        print(f"Successfully committed {count} transactions.")
        
    except Exception as e:
        conn.rollback()
        print(f"Error during commit: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    review_and_commit()
