import os
import glob
import pandas as pd
import logging
from collections import Counter
from datetime import datetime
from kodak.shared.utils import setup_logging, generate_txn_hash
from kodak.shared.db import get_connection, execute_non_query, execute_query
import importlib

RAW_PATH = os.path.join('data', 'new_raw_transactions')
ARCHIVE_PATH = os.path.join(RAW_PATH, 'archive')

def run_ingestion():
    log_file = setup_logging("ingest_new")
    logging.info(f"Starting ingestion process. Log file: {log_file}")
    conn = get_connection()
    
    # 1. Discover Sources Dynamically
    # Scan for subdirectories in RAW_PATH
    subdirs = [d for d in os.listdir(RAW_PATH) if os.path.isdir(os.path.join(RAW_PATH, d)) and d != 'archive']
    
    if not subdirs:
        logging.info("No source directories found in data/new_raw_transactions.")
        conn.close()
        return

    # Generate Batch ID
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.info(f"Generated Batch ID: {batch_id}")

    all_rows = []
    processed_files = [] # Tuples of (full_path, source_name)

    # 2. Iterate Sources
    for source_name in subdirs:
        try:
            # Dynamically import kodak.pipeline.parsers.<source_name>
            module_name = f"kodak.pipeline.parsers.{source_name}"
            parser_module = importlib.import_module(module_name)
            
            if not hasattr(parser_module, 'parse'):
                logging.warning(f"Module '{module_name}' does not have a 'parse' function. Skipping.")
                continue
                
            parser_func = parser_module.parse
            
        except ImportError:
            logging.warning(f"No parser module found for folder '{source_name}' (expected '{module_name}'). Skipping.")
            continue
            
        source_path = os.path.join(RAW_PATH, source_name)
        
        files = glob.glob(os.path.join(source_path, "*"))
        files = [f for f in files if os.path.isfile(f) and not os.path.basename(f).startswith('.')]
        
        if not files:
            continue
            
        logging.info(f"Found {len(files)} files in '{source_name}'.")
        
        for f in files:
            logging.info(f"Parsing {os.path.basename(f)} using {source_name} parser...")
            try:
                rows = parser_func(f)
                all_rows.extend(rows)
                processed_files.append((f, source_name))
            except Exception as e:
                logging.error(f"Failed to parse {f}: {e}")

    if not all_rows:
        logging.info("No rows extracted from any files.")
        conn.close()
        return

    # 3. Load Existing Hashes (Deduplication)
    # Count-based dedup: allows legitimate duplicate transactions (e.g. two transfers
    # of the same amount on the same date) while still catching re-imports.
    existing_txns = execute_query('''
        SELECT t.date, a.external_id as acc_ext, t.type, i.isin, t.amount, t.amount_local
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        LEFT JOIN instruments i ON t.instrument_id = i.id
    ''')

    existing_h1_counts = Counter()
    existing_h2_hashes = set()
    for row in existing_txns:
        isin = row['isin'] if row['isin'] else ''
        amt = row['amount']
        amt_local = row['amount_local']
        h1 = generate_txn_hash(row['date'], row['acc_ext'], row['type'], isin, amt)
        existing_h1_counts[h1] += 1
        # h2 (amount_local) as broad fallback for foreign currency edge cases
        if amt_local:
            h2 = generate_txn_hash(row['date'], row['acc_ext'], row['type'], isin, amt_local)
            existing_h2_hashes.add(h2)

    # 4. Deduplicate within incoming batch (across files)
    # When multiple files cover overlapping periods, the same transaction can
    # appear in more than one file. Build per-hash counts from each source file
    # and take the max across files (not the sum) as the true incoming count.
    per_file_h1 = {}  # source_file -> Counter of h1 hashes
    for item in all_rows:
        isin = item['isin'] if item['isin'] else ''
        h1 = generate_txn_hash(item['date'], item['account_external_id'], item['type'], isin, item['amount'])
        src = item.get('source_file', '')
        if src not in per_file_h1:
            per_file_h1[src] = Counter()
        per_file_h1[src][h1] += 1

    # Max count of each hash across any single file = true expected multiplicity
    all_h1_hashes = set()
    for c in per_file_h1.values():
        all_h1_hashes.update(c.keys())
    max_incoming_h1 = {}
    for h1 in all_h1_hashes:
        max_incoming_h1[h1] = max(c.get(h1, 0) for c in per_file_h1.values())

    # 5. Filter & Stage
    to_stage = []
    skipped_existing = 0
    skipped_batch_dup = 0
    staged_h1_counts = Counter()

    for item in all_rows:
        isin = item['isin'] if item['isin'] else ''
        amt = item['amount']
        amt_local = item['amount_local']

        h1 = generate_txn_hash(item['date'], item['account_external_id'], item['type'], isin, amt)
        h2 = generate_txn_hash(item['date'], item['account_external_id'], item['type'], isin, amt_local) if amt_local else None

        staged_h1_counts[h1] += 1

        # Total allowed = max occurrences in any single file
        allowed = max_incoming_h1.get(h1, 1)

        # Skip if we've already seen enough of this hash (cross-file dedup)
        if staged_h1_counts[h1] > allowed:
            skipped_batch_dup += 1
            continue

        # Skip if already in DB (count-aware)
        if staged_h1_counts[h1] <= existing_h1_counts.get(h1, 0):
            skipped_existing += 1
            continue

        # Fuzzy match via h2 for foreign currency transactions where amount differs
        if h2 and h2 != h1 and h2 in existing_h2_hashes:
            skipped_existing += 1
            continue

        item['hash'] = h1
        item['batch_id'] = batch_id
        to_stage.append(item)

    logging.info(f"Staging {len(to_stage)} transactions (Skipped {skipped_existing} existing, {skipped_batch_dup} batch duplicates).")
    
    if not to_stage:
        return

    # 5. Write to Staging Table
    # We use a Denormalized Staging Table
    execute_non_query('''
        CREATE TABLE IF NOT EXISTS transactions_staging (
            external_id TEXT,
            account_external_id TEXT,
            isin TEXT,
            symbol TEXT,
            date TEXT,
            type TEXT,
            quantity REAL,
            price REAL,
            amount REAL,
            currency TEXT,
            amount_local REAL,
            exchange_rate REAL,
            fee REAL,
            fee_currency TEXT,
            fee_local REAL,
            description TEXT,
            source_file TEXT,
            hash TEXT,
            batch_id TEXT
        )
    ''')

    # Insert
    # We can use pandas to_sql for convenience with the list of dicts
    df_stage = pd.DataFrame(to_stage)
    
    # Ensure all columns match
    # Convert datetime objects to string
    df_stage['date'] = df_stage['date'].astype(str)
    
    try:
        df_stage.to_sql('transactions_staging', conn, if_exists='append', index=False)
        logging.info("Data pushed to staging.")
        
        # 6. Archive Files
        for f_path, source_name in processed_files:
            # Create archive/nordnet/ etc.
            dest_dir = os.path.join(ARCHIVE_PATH, source_name)
            os.makedirs(dest_dir, exist_ok=True)
            
            dest = os.path.join(dest_dir, os.path.basename(f_path))
            
            # Handle duplicates in archive by appending timestamp if needed
            if os.path.exists(dest):
                base, ext = os.path.splitext(os.path.basename(f_path))
                dest = os.path.join(dest_dir, f"{base}_{batch_id}{ext}")
            
            os.replace(f_path, dest)
            logging.info(f"Archived {os.path.basename(f_path)} to {source_name}/")
            
    except Exception as e:
        logging.error(f"Error writing to staging: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    run_ingestion()
