"""Ledger and market-data integrity audit.

Run after every import (add_transactions.ps1 does) and shown on the System
page. Every check returns findings with a level:

    ERROR  the numbers are wrong until this is fixed (pipeline stops)
    WARN   worth a look, numbers still add up
    INFO   context

Checks
    unknown_types        a type in none of the config lists (silently distorts flows)
    date_format          dates must be YYYY-MM-DD (time components break date filters)
    quantity_sign        BUY quantity > 0, SELL quantity < 0
    amount_sign          BUY/WITHDRAWAL/FEE/TAX negative, SELL/DEPOSIT/DIVIDEND positive
    negative_positions   an instrument ends up with fewer than zero shares
    broker_id_duplicates the same broker transaction id stored twice for one account
    reconciliation       ledger cash movement vs the broker's own running balance
    missing_fx_rate      foreign-currency row without an exchange rate
    held_unpriced        current holding with no stored price (carried at cost)
    stale_prices         latest stored price older than STALE_DAYS
    fx_coverage          instrument currency with no stored FX rate
    price_currency       market_prices.currency disagrees with instruments.currency

Usage:
    python -m kodak.maintenance.audit_db          # exit 1 on any ERROR
    python -m kodak.maintenance.audit_db --warn   # also exit 1 on WARN
"""
import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import List

import pandas as pd

from kodak.shared.db import get_db_connection, query_df
from kodak.shared.utils import load_config

logger = logging.getLogger(__name__)

STALE_DAYS = 5
RECON_TOLERANCE = 0.05  # currency units; broker balances are rounded to 2 dp

_cfg = load_config()
BASE_CURRENCY = _cfg.get('base_currency', 'NOK')
_types = _cfg.get('transaction_types', {})
POSITION_TYPES = set(_types.get('inflow', [])) | set(_types.get('outflow', []))
KNOWN_TYPES = POSITION_TYPES | set(_types.get('external_flows', [])) | set(_types.get('other', []))


@dataclass
class Finding:
    level: str          # ERROR | WARN | INFO
    check: str
    message: str
    count: int = 0
    examples: List[str] = field(default_factory=list)


def _held_ids(txns: pd.DataFrame) -> set:
    pos = txns[txns['type'].isin(POSITION_TYPES) & txns['instrument_id'].notna()]
    q = pos.groupby('instrument_id')['quantity'].sum()
    return set(q[q.abs() > 0.001].index.astype(int))


def run_audit() -> List[Finding]:
    f: List[Finding] = []
    with get_db_connection() as conn:
        txns = query_df("""
            SELECT t.id, t.date, t.type, t.instrument_id, t.quantity, t.amount, t.currency,
                   t.amount_local, t.exchange_rate, t.broker_id, t.balance_after, t.balance_currency,
                   a.name AS account, a.external_id AS account_ext, COALESCE(i.symbol, i.isin) AS symbol
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN instruments i ON i.id = t.instrument_id
        """, conn)
        instruments = query_df("SELECT id, symbol, isin, currency, asset_class FROM instruments", conn)
        latest_prices = query_df(
            "SELECT instrument_id, MAX(date) AS latest FROM market_prices GROUP BY instrument_id", conn)
        bad_ccy = query_df("""
            SELECT COUNT(*) AS n FROM market_prices m JOIN instruments i ON i.id = m.instrument_id
            WHERE m.currency IS NOT NULL AND m.currency <> i.currency""", conn)
        fx_ccy = query_df("SELECT DISTINCT from_currency FROM exchange_rates WHERE to_currency = ?",
                          conn, params=(BASE_CURRENCY,))

    if txns.empty:
        return [Finding('ERROR', 'empty', 'The transactions table is empty.')]
    txns['date'] = txns['date'].astype(str)
    for col in ('quantity', 'amount', 'amount_local', 'balance_after', 'exchange_rate'):
        txns[col] = pd.to_numeric(txns[col], errors='coerce')
    txns['quantity'] = txns['quantity'].fillna(0.0)
    txns['amount_local'] = txns['amount_local'].fillna(0.0)

    # --- unknown types ---
    unknown = txns[~txns['type'].isin(KNOWN_TYPES)]
    if not unknown.empty:
        f.append(Finding('ERROR', 'unknown_types',
                         "Transaction types not classified in config.yaml (transaction_types.*)",
                         len(unknown), sorted(unknown['type'].unique().tolist())))

    # --- date format ---
    bad_dates = txns[txns['date'].str.len() != 10]
    if not bad_dates.empty:
        f.append(Finding('ERROR', 'date_format', "Dates that are not plain YYYY-MM-DD",
                         len(bad_dates), bad_dates['date'].head(5).tolist()))

    # --- quantity sign ---
    q_bad = txns[((txns['type'] == 'BUY') & (txns['quantity'] <= 0)) |
                 ((txns['type'] == 'SELL') & (txns['quantity'] >= 0))]
    if not q_bad.empty:
        f.append(Finding('ERROR', 'quantity_sign', "BUY rows must have positive quantity, SELL negative",
                         len(q_bad), [f"{r.date} {r.type} {r.symbol} qty={r.quantity}" for r in q_bad.head(5).itertuples()]))

    # --- amount sign (rights redeemed at 0 and zero-amount corrections are fine) ---
    nonzero = txns[txns['amount_local'].abs() > 0.005]
    neg_types, pos_types = {'BUY', 'WITHDRAWAL', 'FEE', 'TAX', 'TRANSFER_OUT'}, {'SELL', 'DEPOSIT', 'TRANSFER_IN'}
    s_bad = nonzero[(nonzero['type'].isin(neg_types) & (nonzero['amount_local'] > 0)) |
                    (nonzero['type'].isin(pos_types) & (nonzero['amount_local'] < 0))]
    if not s_bad.empty:
        f.append(Finding('WARN', 'amount_sign', "Cash amount has the unexpected sign for its type",
                         len(s_bad), [f"{r.date} {r.account} {r.type} {r.symbol or ''} {r.amount_local:,.2f}" for r in s_bad.head(5).itertuples()]))

    # --- negative end positions ---
    pos = txns[txns['type'].isin(POSITION_TYPES) & txns['instrument_id'].notna()]
    final = pos.groupby(['instrument_id', 'symbol'])['quantity'].sum()
    neg = final[final < -0.001]
    if not neg.empty:
        f.append(Finding('ERROR', 'negative_positions', "Instruments with more shares sold than bought",
                         len(neg), [f"{sym}: {q:,.2f}" for (_, sym), q in neg.items()]))

    # --- broker id duplicates ---
    with_id = txns[txns['broker_id'].notna()]
    dup = with_id[with_id.duplicated(['account_ext', 'broker_id'], keep=False)]
    if not dup.empty:
        f.append(Finding('ERROR', 'broker_id_duplicates', "Same broker transaction id stored more than once",
                         len(dup), dup['broker_id'].astype(str).head(5).tolist()))

    # --- reconciliation against broker balances ---
    f.extend(reconcile(txns))

    # --- FX on foreign rows ---
    foreign = txns[(txns['currency'] != BASE_CURRENCY) & (txns['amount_local'].abs() > 0.005)]
    no_rate = foreign[foreign['exchange_rate'].fillna(0) == 0]
    if not no_rate.empty:
        f.append(Finding('WARN', 'missing_fx_rate', "Foreign-currency rows with no exchange rate",
                         len(no_rate), [f"{r.date} {r.type} {r.symbol or ''} {r.currency}" for r in no_rate.head(5).itertuples()]))

    # --- holdings vs prices ---
    held = _held_ids(txns)
    inst = instruments.set_index('id')
    latest = dict(zip(latest_prices['instrument_id'], latest_prices['latest'].astype(str)))
    # A holding with no price is only a problem if money is tied up in it.
    # Zero-cost positions (subscription rights, allotments) are nominal and
    # expected to sit unpriced until they are redeemed or expire.
    cost = pos.groupby('instrument_id')['amount_local'].sum().abs()
    unpriced = [i for i in held if i not in latest]

    def label(i):
        return inst.loc[i, 'symbol'] or inst.loc[i, 'isin']

    def is_nominal(i):
        return cost.get(i, 0.0) <= 0.005 or inst.loc[i, 'asset_class'] == 'Rights'

    with_cost = [label(i) for i in unpriced if not is_nominal(i)]
    nominal = [label(i) for i in unpriced if is_nominal(i)]
    if with_cost:
        f.append(Finding('WARN', 'held_unpriced', "Current holdings with no stored price (carried at cost)",
                         len(with_cost), with_cost))
    if nominal:
        f.append(Finding('INFO', 'nominal_positions',
                         "Zero-cost positions without a price (rights / allotments awaiting redemption)",
                         len(nominal), nominal))
    if latest:
        newest = max(latest.values())[:10]
        age = (date.today() - date.fromisoformat(newest)).days
        if age > STALE_DAYS:
            f.append(Finding('WARN', 'stale_prices', f"Latest stored price is {age} days old ({newest})", 1))
        lagging = [inst.loc[i, 'symbol'] for i in held if i in latest and latest[i][:10] < newest]
        if lagging:
            f.append(Finding('WARN', 'stale_prices', f"Holdings without a price on the latest date ({newest})",
                             len(lagging), lagging))
    needed = {inst.loc[i, 'currency'] for i in held if i in inst.index} - {BASE_CURRENCY, None}
    missing_fx = sorted(c for c in needed if c not in set(fx_ccy['from_currency']))
    if missing_fx:
        f.append(Finding('ERROR', 'fx_coverage', f"No stored FX rate to {BASE_CURRENCY} for held currencies",
                         len(missing_fx), missing_fx))
    if int(bad_ccy.iloc[0]['n']):
        f.append(Finding('WARN', 'price_currency', "market_prices rows whose currency differs from the instrument",
                         int(bad_ccy.iloc[0]['n'])))

    f.append(Finding('INFO', 'summary',
                     f"{len(txns)} transactions, {len(held)} open positions, "
                     f"{int(txns['broker_id'].notna().sum())} rows carry a broker id", 0))
    return f


def reconcile(txns: pd.DataFrame) -> List[Finding]:
    """Broker balance check: for consecutive rows (in broker booking order) of
    one account and balance currency, the balance must move by exactly the
    cash amount of the row. A drift pinpoints the row whose amount differs
    from the broker's booking, or a missing/extra row just before it."""
    out: List[Finding] = []
    rows = txns[txns['balance_after'].notna() & txns['broker_id'].notna()].copy()
    if rows.empty:
        out.append(Finding('INFO', 'reconciliation', "No broker balances stored yet; run link_broker_ids", 0))
        return out
    rows['order'] = pd.to_numeric(rows['broker_id'], errors='coerce')
    rows['settle'] = rows['amount_local'].where(rows['balance_currency'] == BASE_CURRENCY,
                                                rows['amount'].fillna(0.0))
    drifts, persistent = [], []
    for (acct, ccy), g in rows.sort_values('order').groupby(['account', 'balance_currency']):
        prev = None
        cumulative = 0.0
        for r in g.itertuples():
            if prev is not None:
                drift = (r.balance_after - prev) - r.settle
                if abs(drift) > RECON_TOLERANCE:
                    cumulative += drift
                    drifts.append((acct, ccy, r.date, r.type, r.symbol or '', r.settle, drift, r.id))
            prev = r.balance_after
        # A drift that later reverses (broker booked two legs in a different
        # order than the ids suggest) leaves the balance right; one that
        # persists means the ledger's cash really differs from the broker's.
        if abs(cumulative) > RECON_TOLERANCE:
            persistent.append((acct, ccy, cumulative))
    if persistent:
        out.append(Finding('ERROR', 'reconciliation',
                           "Ledger cash differs from the broker's balance (drift does not reverse)",
                           len(persistent), [f"{a} {c}: {v:+,.2f}" for a, c, v in persistent]))
    if drifts:
        out.append(Finding('WARN' if not persistent else 'INFO', 'reconciliation_rows',
                           "Rows where the balance step differs from the ledger amount (booking-order or fee quirks; net effect above)",
                           len(drifts),
                           [f"{a} {c} {d} {t} {s} ledger={amt:,.2f} drift={dr:+,.2f} (id {i})"
                            for a, c, d, t, s, amt, dr, i in drifts[:10]]))
    if not persistent:
        out.append(Finding('INFO', 'reconciliation',
                           f"{len(rows)} rows reconcile with the broker's running balance", len(rows)))
    return out


def summarize(findings: List[Finding]) -> dict:
    return {lvl: sum(1 for x in findings if x.level == lvl) for lvl in ('ERROR', 'WARN', 'INFO')}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--warn', action='store_true', help='exit non-zero on warnings too')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    findings = run_audit()
    for x in sorted(findings, key=lambda x: ('ERROR', 'WARN', 'INFO').index(x.level)):
        tag = {'ERROR': '[X]', 'WARN': '[!]', 'INFO': '[i]'}[x.level]
        print(f"{tag} {x.check}: {x.message}" + (f" ({x.count})" if x.count else ""))
        for ex in x.examples[:10]:
            print(f"      - {ex}")
    s = summarize(findings)
    print(f"\n{s['ERROR']} error(s), {s['WARN']} warning(s)")
    if s['ERROR'] or (args.warn and s['WARN']):
        sys.exit(1)


if __name__ == '__main__':
    main()
