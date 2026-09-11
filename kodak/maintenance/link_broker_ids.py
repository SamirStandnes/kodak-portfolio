"""One-off: stamp existing ledger rows with the broker's own transaction id and
cash balance, taken from the archived raw exports.

Rows imported before the ledger stored `broker_id` / `balance_after` are
matched back to the export rows that produced them (same parser, same
account, date, type, ISIN and amount). Afterwards every Nordnet row carries
Nordnet's Id and Saldo, which is what `audit_db` reconciles against and what
`ingest` uses for exact de-duplication.

Anything that cannot be matched is printed: export rows with no ledger row
are missing transactions, ledger rows with no export row are extras or rows
whose amount differs from the broker's booking.

Usage:
    python -m kodak.maintenance.link_broker_ids --dry-run
    python -m kodak.maintenance.link_broker_ids
"""
import argparse
import glob
import logging
import os
from collections import defaultdict

import pandas as pd

from kodak.shared.db import get_db_connection, query_df, execute_batch, create_backup
from kodak.shared.utils import setup_logging, generate_txn_hash
from kodak.pipeline.parsers import nordnet

logger = logging.getLogger(__name__)
ARCHIVE = os.path.join('data', 'new_raw_transactions', 'archive', 'nordnet')


def export_rows() -> pd.DataFrame:
    """Every unique Nordnet export row (by Id) across all archived files."""
    items = []
    for f in sorted(glob.glob(os.path.join(ARCHIVE, '*.csv'))):
        parsed = nordnet.parse(f)
        logger.info(f"{os.path.basename(f)}: {len(parsed)} rows")
        items.extend(parsed)
    df = pd.DataFrame(items)
    if df.empty:
        return df
    df = df[df['broker_id'].notna()].drop_duplicates('broker_id')
    df['date'] = df['date'].astype(str).str[:10]
    df['isin'] = df['isin'].fillna('')
    return df.sort_values('broker_id', key=lambda s: s.astype(int)).reset_index(drop=True)


def ledger_rows() -> pd.DataFrame:
    with get_db_connection() as conn:
        df = query_df("""
            SELECT t.id, a.external_id AS account_external_id, t.date, t.type,
                   COALESCE(i.isin, '') AS isin, t.amount, t.amount_local, t.broker_id
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN instruments i ON i.id = t.instrument_id
            WHERE a.broker = 'Nordnet'
            ORDER BY t.id
        """, conn)
    df['date'] = df['date'].astype(str).str[:10]
    return df


def key_exact(r) -> str:
    return generate_txn_hash(r['date'], r['account_external_id'], r['type'], r['isin'], r['amount'])


def key_local(r) -> tuple:
    return (r['account_external_id'], r['date'], r['type'], round(float(r['amount_local'] or 0), 2))


def key_loose(r) -> tuple:
    return (r['account_external_id'], r['date'], round(float(r['amount_local'] or 0), 2))


def match(exports: pd.DataFrame, ledger: pd.DataFrame):
    """Pair export rows with ledger rows, strictest key first. Returns
    (pairs, unmatched_exports, unmatched_ledger)."""
    pairs = []
    exp_left = exports.to_dict('records')
    led_left = ledger.to_dict('records')
    for keyfn, label in ((key_exact, 'exact'), (key_local, 'date+type+amount'), (key_loose, 'date+amount')):
        buckets = defaultdict(list)
        for r in led_left:
            buckets[keyfn(r)].append(r)
        still = []
        matched_ids = set()
        for e in exp_left:
            k = keyfn(e)
            if buckets[k]:
                l = buckets[k].pop(0)
                pairs.append((e, l))
                matched_ids.add(l['id'])
            else:
                still.append(e)
        n = len(exp_left) - len(still)
        logger.info(f"pass '{label}': matched {n}")
        exp_left = still
        led_left = [r for r in led_left if r['id'] not in matched_ids]
    return pairs, exp_left, led_left


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    setup_logging('link_broker_ids')

    exports = export_rows()
    ledger = ledger_rows()
    already = ledger['broker_id'].notna().sum()
    logger.info(f"{len(exports)} unique export rows, {len(ledger)} ledger rows ({already} already linked)")

    todo = ledger[ledger['broker_id'].isna()]
    exports = exports[~exports['broker_id'].isin(set(ledger['broker_id'].dropna().astype(str)))]
    pairs, exp_left, led_left = match(exports, todo)

    if exp_left:
        logger.warning(f"{len(exp_left)} export rows have NO ledger row (missing transactions?):")
        for e in exp_left:
            logger.warning(f"  {e['date']} {e['account_external_id']} {e['type']:<18} {e['amount_local']:>12.2f} {e['balance_currency']}  id={e['broker_id']}  {e['description'][:50]}")
    if led_left:
        logger.warning(f"{len(led_left)} ledger rows have NO export row (extra, or amount differs from broker):")
        for l in led_left:
            logger.warning(f"  {l['date']} {l['account_external_id']} {l['type']:<18} {float(l['amount_local'] or 0):>12.2f}  ledger id={l['id']}")

    if args.dry_run:
        logger.info(f"Dry run: would link {len(pairs)} rows.")
        return

    create_backup('pre_link_broker_ids')
    n = execute_batch(
        "UPDATE transactions SET broker_id = ?, balance_after = ?, balance_currency = ? WHERE id = ?",
        [(e['broker_id'], e['balance_after'], e['balance_currency'], l['id']) for e, l in pairs])
    logger.info(f"Linked {n} ledger rows to broker ids.")


if __name__ == '__main__':
    main()
