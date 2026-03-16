import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

from kodak.shared.db import get_connection, get_db_connection, execute_query, query_df
from kodak.shared.market_data import get_historical_prices_by_date, get_forward_dividends, get_exchange_rate
from kodak.shared.utils import load_config

# --- Configuration ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

# --- Transaction Type Classification (loaded from config) ---
_txn_types = config.get('transaction_types', {})
INFLOW_TYPES = _txn_types.get('inflow', ['BUY', 'DEPOSIT', 'TRANSFER_IN'])
OUTFLOW_TYPES = _txn_types.get('outflow', ['SELL', 'WITHDRAWAL', 'TRANSFER_OUT'])
EXTERNAL_FLOW_TYPES = _txn_types.get('external_flows', ['DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT'])

def get_internal_splits() -> Dict[str, List[Tuple[pd.Timestamp, float]]]:
    """
    Discovers stock splits from 'BYTTE' (Exchange) transactions in the DB.

    Returns:
        Dictionary mapping symbol to list of (date, split_ratio) tuples.
    """
    query = """
        SELECT t.date, i.symbol, t.type, t.quantity
        FROM transactions t
        JOIN instruments i ON t.instrument_id = i.id
        WHERE t.type LIKE 'BYTTE %'
        ORDER BY t.date, i.symbol
    """
    with get_db_connection() as conn:
        df = query_df(query, conn)

    splits = {}
    # Group by date and symbol to find the IN/OUT pairs
    for (date, symbol), group in df.groupby([df['date'].str[:10], 'symbol']):
        row_in = group[group['type'] == 'BYTTE INNLEGG VP']
        row_out = group[group['type'] == 'BYTTE UTTAK VP']
        
        if not row_in.empty and not row_out.empty:
            qty_in = row_in.iloc[0]['quantity']
            qty_out = abs(row_out.iloc[0]['quantity'])
            if qty_out != 0:
                ratio = qty_in / qty_out
                if symbol not in splits: splits[symbol] = []
                splits[symbol].append((pd.to_datetime(date), ratio))
    return splits

def get_adjusted_qty(symbol: str, raw_qty: float, ref_date: str, split_map: Dict[str, List[Tuple[pd.Timestamp, float]]]) -> float:
    """
    Adjusts raw quantity to today's scale based on splits occurring after ref_date.

    Args:
        symbol: The ticker symbol
        raw_qty: Original quantity from the ledger
        ref_date: Reference date (YYYY-MM-DD)
        split_map: Dictionary from get_internal_splits()

    Returns:
        Adjusted quantity accounting for splits
    """
    if symbol not in split_map or raw_qty == 0:
        return raw_qty
        
    ts_ref = pd.Timestamp(ref_date)
    ratio = 1.0
    for split_date, split_ratio in split_map[symbol]:
        if split_date > ts_ref:
            ratio *= split_ratio
    return raw_qty * ratio

def get_price_with_fallback(symbol: str, price_dict: dict, ref_date: str, missing_log: list = None) -> float:
    """
    Attempts to get a price for a symbol, with fallback to database lookups.

    Args:
        symbol: The ticker symbol or FX pair (e.g., 'AAPL' or 'USDNOK=X')
        price_dict: Dictionary of {symbol: price} from Yahoo Finance
        ref_date: Reference date for fallback lookups (YYYY-MM-DD)
        missing_log: Optional list to append missing price info for debugging

    Returns:
        The price as a float, or 0.0 if not found
    """
    # 1. Try the provided price dictionary (Yahoo data)
    price = price_dict.get(symbol, 0.0)
    if price > 0:
        return price

    # 2. Try Database (Nearest Transaction)
    # Handle FX Pairs (e.g. HKDNOK=X)
    if symbol.endswith(f"{BASE_CURRENCY}=X"):
        curr = symbol.replace(f"{BASE_CURRENCY}=X", "")
        query = """
            SELECT t.exchange_rate FROM transactions t
            JOIN instruments i ON t.instrument_id = i.id
            WHERE i.currency = ? AND t.exchange_rate > 0
            ORDER BY ABS(strftime('%J', t.date) - strftime('%J', ?))
            LIMIT 1
        """
        with get_db_connection() as conn:
            row = conn.execute(query, (curr, ref_date)).fetchone()
        if row:
            if missing_log is not None:
                missing_log.append({'symbol': symbol, 'date': ref_date, 'type': 'FX_FALLBACK', 'price': row[0]})
            return row[0]
        return 1.0  # Default to 1.0 if no FX history found

    # Handle Standard Instruments
    query = """
        SELECT price FROM transactions t
        JOIN instruments i ON t.instrument_id = i.id
        WHERE i.symbol = ? AND t.price > 0 AND t.type IN ('BUY', 'SELL')
        ORDER BY ABS(strftime('%J', t.date) - strftime('%J', ?))
        LIMIT 1
    """
    with get_db_connection() as conn:
        row = conn.execute(query, (symbol, ref_date)).fetchone()

    if row:
        if missing_log is not None:
            missing_log.append({'symbol': symbol, 'date': ref_date, 'type': 'DB_FALLBACK', 'price': row[0]})
        return row[0]

    if missing_log is not None:
        missing_log.append({'symbol': symbol, 'date': ref_date, 'type': 'MISSING', 'price': 0.0})
    return 0.0


def xirr(transactions: List[Tuple[datetime, float]]) -> float:
    """
    Calculates the Extended Internal Rate of Return (XIRR) using Newton-Raphson.

    Args:
        transactions: List of (date, amount) tuples. Negative = outflow, Positive = inflow.

    Returns:
        The annualized return rate as a decimal (e.g., 0.15 for 15%)
    """
    if not transactions: return 0.0
    transactions.sort(key=lambda x: x[0])
    amounts = [t[1] for t in transactions]
    if all(a >= 0 for a in amounts) or all(a <= 0 for a in amounts): return 0.0
    dates = [t[0] for t in transactions]; d0 = dates[0]
    years = [(d - d0).days / 365.0 for d in dates]
    rate = 0.1
    for _ in range(50):
        f = 0.0; df = 0.0
        for i, year in enumerate(years):
            a = amounts[i]; r_plus_1 = (1 + rate)
            if r_plus_1 <= 0: r_plus_1 = 1e-6 
            exp = r_plus_1 ** year
            f += a / exp
            df -= a * year * (r_plus_1 ** (year - 1)) / (exp ** 2)
        if abs(f) < 1e-6: return float(rate.real) if hasattr(rate, 'real') else float(rate)
        if df == 0: break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-6: return float(new_rate.real) if hasattr(new_rate, 'real') else float(new_rate)
        rate = new_rate
    return float(rate.real) if hasattr(rate, 'real') else float(rate)

def get_yearly_contribution(target_year: str) -> Tuple[pd.DataFrame, float, List[Dict[str, Any]]]:
    query = """
        SELECT t.date, t.type, t.instrument_id, t.quantity, t.amount_local, t.fee_local, i.symbol, i.currency
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        WHERE t.date <= ?
        ORDER BY t.date, t.id
    """
    with get_db_connection() as conn:
        df = query_df(query, conn, params=(f"{target_year}-12-31",))
    if df.empty: return pd.DataFrame(), 0.0
    
    soy_date = f"{int(target_year)-1}-12-31"
    # For current year, use today's date instead of Dec 31
    today = datetime.now().strftime("%Y-%m-%d")
    eoy_date = today if str(target_year) == today[:4] else f"{target_year}-12-31"
    split_map = get_internal_splits()

    # 1. External Flows (Portfolio Level)
    flow_txns = df[df['type'].isin(EXTERNAL_FLOW_TYPES)].copy()
    flow_txns['date_obj'] = pd.to_datetime(flow_txns['date'], format='mixed')
    yearly_detailed_flows = {}
    for _, row in flow_txns.iterrows():
        y = str(row['date'])[:4]; d = row['date_obj']; amt = row['amount_local']
        if y not in yearly_detailed_flows: yearly_detailed_flows[y] = []
        yearly_detailed_flows[y].append((d, -amt))

    # 2. Replay Loop State
    holdings = {}; soy_holdings = {}; eoy_holdings = {}; pos_flows = {}; dividends = {}; detailed_flows = {}
    cash_soy = 0.0; cash_eoy = 0.0; cash_flows_ext = 0.0
    fees_t = 0.0; int_t = 0.0; tax_t = 0.0
    sym_currency = {}

    for _, row in df.iterrows():
        t_date = row['date'][:10]; t_date_obj = pd.to_datetime(t_date); t_year = t_date[:4]; t_type = row['type']; qty = row['quantity']; amt = row['amount_local']
        sym = row['symbol']
        
        # Track Cash
        if t_date <= soy_date: cash_soy += amt
        cash_eoy += amt
        
        if t_year == target_year:
            if t_type in EXTERNAL_FLOW_TYPES: cash_flows_ext += amt
            elif t_type == 'FEE': fees_t += amt
            elif t_type == 'INTEREST': int_t += amt
            elif t_type == 'TAX': tax_t += amt
            f_emb = row.get('fee_local', 0.0)
            if pd.notna(f_emb) and f_emb > 0: fees_t -= abs(f_emb)
        
        # Track Positions
        if sym:
            sym_currency[sym] = row['currency']
            if sym not in holdings: holdings[sym] = {'qty': 0.0, 'cost': 0.0}
            h = holdings[sym]
            
            if t_type in ['BUY', 'SELL', 'INNLØSN. UTTAK VP', 'TILDELING INNLEGG RE', 'BYTTE INNLEGG VP', 'BYTTE UTTAK VP', 'TRANSFER_IN', 'TRANSFER_OUT', 'EMISJON INNLEGG VP']:
                # Special Split Handling
                if t_type == 'BYTTE UTTAK VP':
                    h['qty'] += qty # negative
                    # Do NOT reduce cost
                elif t_type == 'BYTTE INNLEGG VP':
                    h['qty'] += qty
                    h['cost'] += abs(amt)
                elif t_type in INFLOW_TYPES: h['qty'] += qty; h['cost'] += abs(amt)
                elif t_type in OUTFLOW_TYPES:
                    if h['qty'] > 0: h['cost'] -= (h['cost'] / h['qty']) * abs(qty)
                    h['qty'] += qty
            
            # Save Snapshots
            if t_date <= soy_date: soy_holdings[sym] = h.copy()
            eoy_holdings[sym] = h.copy()

            if t_year == target_year and t_type in ['BUY', 'SELL', 'INNLØSN. UTTAK VP', 'DIVIDEND']:
                if sym not in detailed_flows: detailed_flows[sym] = []
                detailed_flows[sym].append((t_date_obj, amt))
                if t_type == 'DIVIDEND': dividends[sym] = dividends.get(sym, 0.0) + amt
                else: pos_flows[sym] = pos_flows.get(sym, 0.0) + amt

    # Cleanup tiny positions
    soy_holdings = {k: v for k, v in soy_holdings.items() if abs(v['qty']) > 0.001}
    eoy_holdings = {k: v for k, v in eoy_holdings.items() if abs(v['qty']) > 0.001}

    # Value Snapshots
    all_pos_syms = set(soy_holdings.keys()) | set(eoy_holdings.keys())
    fetch_list = list(all_pos_syms)
    fx_map = {}
    for sym in all_pos_syms:
        c = sym_currency.get(sym, BASE_CURRENCY)
        if c != BASE_CURRENCY:
            pair = f"{c}{BASE_CURRENCY}=X"; fetch_list.append(pair); fx_map[c] = pair
    
    p_soy = get_historical_prices_by_date(fetch_list, soy_date)
    p_eoy = get_historical_prices_by_date(fetch_list, eoy_date)

    missing_prices = []

    def calc_snapshot_eq(h_dict, p_dict, cash_v, ref_date):
        total_v = 0.0
        for s, h in h_dict.items():
            if abs(h['qty']) < 0.001: continue
            p = get_price_with_fallback(s, p_dict, ref_date, missing_prices)
            curr = sym_currency.get(s, BASE_CURRENCY)
            r = 1.0
            if curr != BASE_CURRENCY:
                pair = fx_map.get(curr)
                r = get_price_with_fallback(pair, p_dict, ref_date, missing_prices)

            adj_q = get_adjusted_qty(s, h['qty'], ref_date, split_map)
            total_v += (adj_q * p * r) if p > 0 else h['cost']
        return total_v + cash_v

    eq_soy = calc_snapshot_eq(soy_holdings, p_soy, cash_soy, soy_date)
    eq_eoy = calc_snapshot_eq(eoy_holdings, p_eoy, cash_eoy, eoy_date)
    total_portfolio_profit = eq_eoy - eq_soy - cash_flows_ext
    
    # Portfolio XIRR
    x_flows = []
    if eq_soy > 0: x_flows.append((pd.Timestamp(soy_date), -eq_soy))
    x_flows.extend(yearly_detailed_flows.get(target_year, []))
    if eq_eoy > 0: x_flows.append((pd.Timestamp(eoy_date), eq_eoy))
    total_portfolio_xirr = xirr(x_flows) * 100

    # Build Result
    report = []
    sum_pos_profit = 0.0
    for s in all_pos_syms:
        def get_v(h_d, p_d, ref_d):
            h = h_d.get(s, {'qty': 0.0, 'cost': 0.0})
            p = get_price_with_fallback(s, p_d, ref_d, missing_prices)
            curr = sym_currency.get(s, BASE_CURRENCY)
            r = 1.0
            if curr != BASE_CURRENCY:
                pair = fx_map.get(curr)
                r = get_price_with_fallback(pair, p_d, ref_d, missing_prices)
            aq = get_adjusted_qty(s, h['qty'], ref_d, split_map)
            return (aq * p * r) if p > 0 else h['cost']
        vs = get_v(soy_holdings, p_soy, soy_date)
        ve = get_v(eoy_holdings, p_eoy, eoy_date)
        nf = pos_flows.get(s, 0.0)
        dv = dividends.get(s, 0.0)
        profit = ve - vs + nf + dv; sum_pos_profit += profit
        i_x_flows = []
        if vs > 0: i_x_flows.append((pd.Timestamp(soy_date), -vs))
        i_x_flows.extend(detailed_flows.get(s, []))
        if ve > 0: i_x_flows.append((pd.Timestamp(eoy_date), ve))
        i_irr = xirr(i_x_flows) * 100
        if abs(vs) > 1 or abs(ve) > 1 or abs(profit) > 1:
            report.append({'Symbol': s, 'SOY Value': vs, 'EOY Value': ve, 'Net Additions': -nf, 'Dividends': dv, 'Profit': profit, 'IRR %': i_irr})

    float_profit = total_portfolio_profit - sum_pos_profit
    c_fx = float_profit - (fees_t + int_t + tax_t)
    if abs(fees_t) > 0.1: report.append({'Symbol': '[Fees]', 'SOY Value': 0, 'EOY Value': 0, 'Net Additions': 0, 'Dividends': 0, 'Profit': fees_t, 'IRR %': 0})
    if abs(int_t) > 0.1: report.append({'Symbol': '[Interest]', 'SOY Value': 0, 'EOY Value': 0, 'Net Additions': 0, 'Dividends': 0, 'Profit': int_t, 'IRR %': 0})
    if abs(tax_t) > 0.1: report.append({'Symbol': '[Div Tax]', 'SOY Value': 0, 'EOY Value': 0, 'Net Additions': 0, 'Dividends': 0, 'Profit': tax_t, 'IRR %': 0})
    report.append({'Symbol': '[Cash FX & Float]*', 'SOY Value': cash_soy, 'EOY Value': cash_eoy, 'Net Additions': cash_flows_ext, 'Dividends': 0, 'Profit': c_fx, 'IRR %': 0.0})
    df_res = pd.DataFrame(report)
    df_res['Contribution %'] = (df_res['Profit'] / total_portfolio_profit) * total_portfolio_xirr if abs(total_portfolio_profit) > 1 else 0.0
    return df_res.sort_values('Profit', ascending=False), total_portfolio_xirr, missing_prices

def get_yearly_equity_curve() -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    query = """
        SELECT t.date, t.type, t.instrument_id, t.quantity, t.amount_local, i.symbol, i.currency
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        ORDER BY t.date, t.id
    """
    with get_db_connection() as conn:
        df = query_df(query, conn)
    if df.empty: return pd.DataFrame()
    df['year'] = df['date'].str[:4]; years = sorted(df['year'].unique())
    split_map = get_internal_splits()
    holdings = {}; cash_balance = 0.0; results = []
    # 1. External Flows (Portfolio Level)
    flow_txns = df[df['type'].isin(EXTERNAL_FLOW_TYPES)].copy()
    flow_txns['date_obj'] = pd.to_datetime(flow_txns['date'], format='mixed')
    y_flows = {}
    for _, row in flow_txns.iterrows():
        y = row['year']; d = row['date_obj']; amt = row['amount_local']
        if y not in y_flows: y_flows[y] = []
        y_flows[y].append((d, -amt))
    previous_equity = 0.0
    missing_prices = []

    for year in years:
        for _, row in df[df['year'] == year].iterrows():
            t_type = row['type']; qty = row['quantity']; amt = row['amount_local']; cash_balance += amt; sym = row['symbol']
            if sym:
                if sym not in holdings: holdings[sym] = {'qty': 0.0, 'cost': 0.0, 'curr': row['currency']}
                h = holdings[sym]
                # Split Handling
                if t_type == 'BYTTE UTTAK VP':
                    h['qty'] += qty
                elif t_type == 'BYTTE INNLEGG VP':
                    h['qty'] += qty
                    h['cost'] += abs(amt)
                elif t_type in INFLOW_TYPES: h['qty'] += qty; h['cost'] += abs(amt)
                elif t_type in OUTFLOW_TYPES:
                    if h['qty'] > 0: h['cost'] -= (h['cost'] / h['qty']) * abs(qty)
                    h['qty'] += qty
        to_remove = [k for k, v in holdings.items() if abs(v['qty']) < 0.001]
        for k in to_remove: del holdings[k]
        # For current year, use today's date instead of Dec 31
        today = datetime.now().strftime("%Y-%m-%d")
        date_str = today if year == today[:4] else f"{year}-12-31"
        fetch_list = list(holdings.keys())
        for s in list(holdings.keys()):
            if holdings[s]['curr'] != BASE_CURRENCY:
                pair = f"{holdings[s]['curr']}{BASE_CURRENCY}=X"
                if pair not in fetch_list: fetch_list.append(pair)
        price_data = get_historical_prices_by_date(fetch_list, date_str)
        equity_holdings = 0.0
        for s, h in holdings.items():
            price = get_price_with_fallback(s, price_data, date_str, missing_prices)
            rate = 1.0
            if h['curr'] != BASE_CURRENCY:
                pair = f"{h['curr']}{BASE_CURRENCY}=X"
                rate = get_price_with_fallback(pair, price_data, date_str, missing_prices)
            aq = get_adjusted_qty(s, h['qty'], date_str, split_map)
            val = (aq * price * rate) if price > 0 else h['cost']
            
            equity_holdings += val
        total_equity = equity_holdings + cash_balance
        x_flows = []
        if previous_equity > 0: x_flows.append((pd.Timestamp(f"{int(year)-1}-12-31"), -previous_equity))
        x_flows.extend(y_flows.get(year, []))
        if total_equity > 0: x_flows.append((pd.Timestamp(date_str), total_equity))
        
        results.append({'year': year, 'start_equity': previous_equity, 'net_flow': sum([-a for _, a in y_flows.get(year, [])]), 'end_equity': total_equity, 'profit': total_equity - previous_equity - sum([-a for _, a in y_flows.get(year, [])]), 'return_pct': xirr(x_flows) * 100})
        previous_equity = total_equity
    return pd.DataFrame(results), missing_prices

def get_holdings(date: Optional[str] = None) -> pd.DataFrame:
    date_filter = ""
    params = []
    if date:
        date_filter = "AND t.date <= ?"
        params = [date]
    query = f"""
        SELECT t.instrument_id, t.type, t.quantity, t.amount_local, t.date, i.symbol, i.isin
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        WHERE t.instrument_id IS NOT NULL {date_filter}
        ORDER BY t.instrument_id, t.date
    """
    with get_db_connection() as conn:
        df = query_df(query, conn, params=tuple(params) if params else None)
    if df.empty: return pd.DataFrame()
    final_holdings = []
    for inst_id, group in df.groupby('instrument_id'):
        total_qty = 0.0; total_cost = 0.0; first_row = group.iloc[0]
        for _, row in group.iterrows():
            t_type = row['type']
            
            # Special handling for Internal Splits/Exchanges (Same Instrument)
            # We preserve the cost basis on withdrawal and carry it over to the new shares.
            if t_type == 'BYTTE UTTAK VP':
                total_qty += row['quantity'] # quantity is negative
                continue
            
            if t_type == 'BYTTE INNLEGG VP':
                total_qty += row['quantity']
                total_cost += abs(row['amount_local']) # Should be 0, but add just in case
                continue

            if any(t in t_type for t in INFLOW_TYPES): total_qty += row['quantity']; total_cost += abs(row['amount_local'])
            elif any(t in t_type for t in OUTFLOW_TYPES):
                if total_qty > 0: total_cost -= (total_cost / total_qty) * abs(row['quantity'])
                total_qty += row['quantity']
        if abs(total_qty) > 0.001: final_holdings.append({'instrument_id': inst_id, 'symbol': first_row['symbol'], 'isin': first_row['isin'], 'quantity': total_qty, 'cost_basis_local': max(0, total_cost)})
    return pd.DataFrame(final_holdings)

def get_income_and_costs() -> Dict[str, float]:
    row = execute_query('''
        SELECT
            SUM(CASE WHEN type = 'DIVIDEND' THEN amount_local ELSE 0 END) as dividends,
            SUM(CASE WHEN type = 'INTEREST' THEN ABS(amount_local) ELSE 0 END) as interest,
            SUM(CASE WHEN type = 'FEE' THEN ABS(amount_local) ELSE fee_local END) as fees
        FROM transactions
    ''')[0]
    return {'dividends': row['dividends'] or 0, 'interest': row['interest'] or 0, 'fees': row['fees'] or 0}


def get_fee_analysis() -> pd.DataFrame:
    """
    Analyzes trading fees by broker.

    Returns DataFrame with columns:
        - broker: Broker name
        - total_traded: Total traded volume (abs value of BUY + SELL) in base currency
        - total_fees: Total fees paid in base currency
        - fee_per_100: Fee cost per 100 base currency traded
        - num_trades: Number of BUY/SELL transactions
    """
    query = """
        SELECT
            a.broker,
            ABS(t.amount_local) as traded_amount,
            COALESCE(t.fee_local, 0) as fee
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.type IN ('BUY', 'SELL')
    """
    with get_db_connection() as conn:
        df = query_df(query, conn)

    if df.empty:
        return pd.DataFrame(columns=['broker', 'total_traded', 'total_fees', 'fee_per_100', 'num_trades'])

    result = df.groupby('broker').agg(
        total_traded=('traded_amount', 'sum'),
        total_fees=('fee', 'sum'),
        num_trades=('traded_amount', 'count')
    ).reset_index()

    result['fee_per_100'] = (result['total_fees'] / result['total_traded'] * 100).round(4)
    result = result.sort_values('fee_per_100')

    return result[['broker', 'total_traded', 'total_fees', 'fee_per_100', 'num_trades']]


def get_platform_fees() -> pd.DataFrame:
    """
    Analyzes platform/custody fees by broker (non-trading fees).

    Returns DataFrame with columns:
        - broker: Broker name
        - total_fees: Total platform fees in base currency
        - monthly_avg: Average monthly fee
        - num_charges: Number of fee transactions
    """
    query = """
        SELECT
            a.broker,
            ABS(t.amount_local) as fee_amount,
            t.date
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        WHERE t.type = 'FEE'
    """
    with get_db_connection() as conn:
        df = query_df(query, conn)

    if df.empty:
        return pd.DataFrame(columns=['broker', 'total_fees', 'monthly_avg', 'num_charges'])

    # Calculate months span for average
    df['date'] = pd.to_datetime(df['date'], format='mixed')

    result = df.groupby('broker').agg(
        total_fees=('fee_amount', 'sum'),
        num_charges=('fee_amount', 'count'),
        first_date=('date', 'min'),
        last_date=('date', 'max')
    ).reset_index()

    # Calculate monthly average
    result['months'] = ((result['last_date'] - result['first_date']).dt.days / 30.44).clip(lower=1)
    result['monthly_avg'] = (result['total_fees'] / result['months']).round(2)

    result = result.sort_values('monthly_avg', ascending=False)

    return result[['broker', 'total_fees', 'monthly_avg', 'num_charges']]


def get_total_xirr() -> float:
    with get_db_connection() as conn:
        df = query_df("SELECT date, type, amount_local FROM transactions", conn)
    if df.empty: return 0.0
    # 1. External Flows (Portfolio Level)
    flow_txns = df[df['type'].isin(EXTERNAL_FLOW_TYPES)].copy()
    flow_txns['date_obj'] = pd.to_datetime(flow_txns['date'], format='mixed')
    x_flows = [(row['date_obj'], -row['amount_local']) for _, row in flow_txns.iterrows()]
    df_h = get_holdings()
    total_mv = 0.0
    if not df_h.empty:
        from kodak.shared.market_data import get_latest_prices, get_exchange_rate
        prices = get_latest_prices(df_h['instrument_id'].tolist())
        for _, r in df_h.iterrows():
            m = prices.get(r['instrument_id'])
            if m:
                p, c = m; fx = get_exchange_rate(c, BASE_CURRENCY) if c != BASE_CURRENCY else 1.0
                total_mv += r['quantity'] * p * fx
            else: total_mv += r['cost_basis_local']
    curr_eq = total_mv + df['amount_local'].sum()
    if curr_eq > 0: x_flows.append((pd.Timestamp.now(), curr_eq))
    return xirr(x_flows) * 100

def get_dividend_details():
    """
    Returns detailed dividend data:
    1. Yearly totals
    2. Top payers (Current Year)
    3. Top payers (All Time)
    """
    current_year = datetime.now().strftime('%Y')

    with get_db_connection() as conn:
        # 1. Yearly
        df_yearly = query_df("""
            SELECT
                strftime('%Y', date) as year,
                SUM(amount_local) as total
            FROM transactions
            WHERE type = 'DIVIDEND'
            GROUP BY year
            ORDER BY year
        """, conn)

        # 2. By Ticker (Current Year)
        df_current_year = query_df("""
            SELECT
                COALESCE(i.symbol, i.isin) as symbol,
                SUM(t.amount_local) as total
            FROM transactions t
            LEFT JOIN instruments i ON t.instrument_id = i.id
            WHERE t.type = 'DIVIDEND' AND t.date LIKE ?
            GROUP BY symbol
            ORDER BY total DESC
        """, conn, params=(f"{current_year}%",))

        # 3. By Ticker (All Time)
        df_all_time = query_df("""
            SELECT
                COALESCE(i.symbol, i.isin) as symbol,
                SUM(t.amount_local) as total
            FROM transactions t
            LEFT JOIN instruments i ON t.instrument_id = i.id
            WHERE t.type = 'DIVIDEND'
            GROUP BY symbol
            ORDER BY total DESC
        """, conn)

    return df_yearly, df_current_year, df_all_time


def get_dividend_forecast() -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Estimates annual dividend income using a hybrid approach:
    1. Primary: Yahoo Finance forward dividend rate (indicated annual dividend)
    2. Fallback: Trailing 12-month (TTM) dividends from transaction history

    Returns:
        Tuple of (details_df, summary_dict)

        details_df columns:
            - symbol: Stock symbol
            - quantity: Current shares held
            - source: 'yahoo' or 'ttm' (data source)
            - dividend_per_share: Annual dividend per share (in asset currency)
            - currency: Asset currency
            - annual_estimate: Estimated annual dividend (in asset currency)
            - annual_estimate_local: Estimated annual dividend (in base currency)

        summary_dict:
            - total_estimate_local: Total estimated annual dividends in base currency
            - yahoo_count: Number of holdings using Yahoo data
            - ttm_count: Number of holdings using TTM fallback
            - no_data_count: Number of holdings with no dividend data
    """
    holdings = get_holdings()
    if holdings.empty:
        return pd.DataFrame(), {'total_estimate_local': 0, 'yahoo_count': 0, 'ttm_count': 0, 'no_data_count': 0}

    # Get symbols for Yahoo lookup
    symbols = holdings['symbol'].dropna().tolist()

    # Fetch forward dividends from Yahoo Finance
    yahoo_dividends = get_forward_dividends(symbols)

    # Get TTM dividends from transaction history as fallback
    with get_db_connection() as conn:
        ttm_df = query_df("""
            SELECT
                i.symbol,
                i.currency,
                SUM(t.amount) as ttm_total,
                COUNT(*) as num_payments
            FROM transactions t
            LEFT JOIN instruments i ON t.instrument_id = i.id
            WHERE t.type = 'DIVIDEND'
            AND t.date >= date('now', '-12 months')
            GROUP BY t.instrument_id
        """, conn)

    ttm_by_symbol = {row['symbol']: row for _, row in ttm_df.iterrows()}

    # Get instrument currencies from DB
    with get_db_connection() as conn:
        currencies_df = query_df(
            "SELECT symbol, currency FROM instruments WHERE symbol IS NOT NULL", conn)
    currency_map = dict(zip(currencies_df['symbol'], currencies_df['currency']))

    results = []
    yahoo_count = 0
    ttm_count = 0
    no_data_count = 0

    for _, row in holdings.iterrows():
        symbol = row['symbol']
        quantity = row['quantity']

        if not symbol or pd.isna(symbol):
            no_data_count += 1
            continue

        # Try Yahoo Finance first
        if symbol in yahoo_dividends:
            yf_data = yahoo_dividends[symbol]
            div_per_share = yf_data['dividend_rate']
            currency = yf_data['currency'] or currency_map.get(symbol, 'USD')
            annual_estimate = div_per_share * quantity
            source = 'yahoo'
            yahoo_count += 1

        # Fall back to TTM
        elif symbol in ttm_by_symbol:
            ttm_data = ttm_by_symbol[symbol]
            # Get holdings at time of dividends to calculate per-share
            # For simplicity, use total TTM as the estimate (assumes same position size)
            annual_estimate = ttm_data['ttm_total']
            currency = ttm_data['currency'] or currency_map.get(symbol, BASE_CURRENCY)
            div_per_share = annual_estimate / quantity if quantity > 0 else 0
            source = 'ttm'
            ttm_count += 1

        else:
            # No dividend data available
            no_data_count += 1
            continue

        # Convert to local currency
        fx_rate = get_exchange_rate(currency, BASE_CURRENCY) if currency != BASE_CURRENCY else 1.0
        annual_estimate_local = annual_estimate * fx_rate

        results.append({
            'symbol': symbol,
            'quantity': quantity,
            'source': source,
            'dividend_per_share': round(div_per_share, 4),
            'currency': currency,
            'annual_estimate': round(annual_estimate, 2),
            'annual_estimate_local': round(annual_estimate_local, 2)
        })

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values('annual_estimate_local', ascending=False)

    total_local = df['annual_estimate_local'].sum() if not df.empty else 0

    summary = {
        'total_estimate_local': round(total_local, 2),
        'yahoo_count': yahoo_count,
        'ttm_count': ttm_count,
        'no_data_count': no_data_count
    }

    return df, summary


def get_interest_details():
    """
    Returns detailed interest data:
    1. Yearly totals
    2. By Currency
    3. Top Payments
    """
    with get_db_connection() as conn:
        # 1. Yearly
        df_yearly = query_df("""
            SELECT
                strftime('%Y', date) as year,
                SUM(ABS(amount_local)) as total
            FROM transactions
            WHERE type = 'INTEREST'
            GROUP BY year
            ORDER BY year
        """, conn)

        # 2. By Currency
        df_currency = query_df("""
            SELECT
                currency,
                SUM(ABS(amount_local)) as total
            FROM transactions
            WHERE type = 'INTEREST'
            GROUP BY currency
            ORDER BY total DESC
        """, conn)

        # 3. Recent Payments
        df_top = query_df("""
            SELECT
                date,
                currency,
                ABS(amount) as amount,
                ABS(amount_local) as amount_local,
                source_file
            FROM transactions
            WHERE type = 'INTEREST'
            ORDER BY date DESC
            LIMIT 50
        """, conn)

    return df_yearly, df_currency, df_top

def get_fee_details():
    """
    Returns detailed fee data:
    1. Yearly totals
    2. By Currency
    3. Top Payments
    """
    with get_db_connection() as conn:
        # 1. Yearly
        df_yearly = query_df("""
            SELECT
                strftime('%Y', date) as year,
                SUM(
                    CASE
                        WHEN type = 'FEE' THEN ABS(amount_local)
                        ELSE fee_local
                    END
                ) as total
            FROM transactions
            WHERE type = 'FEE' OR fee_local > 0
            GROUP BY year
            ORDER BY year
        """, conn)

        # 2. By Currency
        df_currency = query_df("""
            SELECT
                currency,
                SUM(
                    CASE
                        WHEN type = 'FEE' THEN ABS(amount_local)
                        ELSE fee_local
                    END
                ) as total
            FROM transactions
            WHERE type = 'FEE' OR fee_local > 0
            GROUP BY currency
            ORDER BY total DESC
        """, conn)

        # 3. Recent Fees
        df_top = query_df("""
            SELECT
                date,
                currency,
                CASE
                    WHEN type = 'FEE' THEN ABS(amount_local)
                    ELSE fee_local
                END as amount_local,
                source_file
            FROM transactions
            WHERE type = 'FEE' OR fee_local > 0
            ORDER BY date DESC
            LIMIT 50
        """, conn)

    return df_yearly, df_currency, df_top

def get_fx_performance():
    """
    Calculates Realized P&L, Remaining Holdings, and Cost Basis for foreign currency.
    Includes ALL transaction types (BUY, SELL, DIVIDEND, INTEREST, CURRENCY_EXCHANGE, etc.)
    to compute the true foreign currency cash balance.
    Returns a DataFrame.
    """
    # Fetch all transactions in non-base currencies
    query = f"""
        SELECT
            date,
            currency,
            amount as quantity,
            amount_local
        FROM transactions
        WHERE currency != '{BASE_CURRENCY}'
        ORDER BY date, id
    """

    with get_db_connection() as conn:
        df = query_df(query, conn)

    if df.empty:
        return pd.DataFrame()

    results = []

    # Process each currency
    for currency, group in df.groupby('currency'):
        holdings = 0.0
        total_cost = 0.0
        realized_pl = 0.0

        # Sort just in case
        group = group.sort_values('date')

        for _, row in group.iterrows():
            qty = row['quantity']
            val_nok = row['amount_local']

            if qty > 0:
                # BUY (Inflow of Foreign Currency)
                holdings += qty
                total_cost += val_nok

            elif qty < 0:
                # SELL (Outflow of Foreign Currency)
                if holdings <= 0:
                    cost_portion = 0
                else:
                    portion = abs(qty) / holdings
                    portion = min(portion, 1.0)
                    cost_portion = total_cost * portion

                proceeds = abs(val_nok)
                gain = proceeds - cost_portion
                realized_pl += gain

                # Update Inventory
                holdings += qty
                total_cost -= cost_portion

                if abs(holdings) < 0.01:
                    holdings = 0
                    total_cost = 0

        results.append({
            'currency': currency,
            'realized_pl_nok': realized_pl,
            'holdings': holdings,
            'cost_basis_nok': total_cost
        })

    return pd.DataFrame(results)


def get_fx_performance_detailed():
    """
    Comprehensive FX P&L calculation including both cash and securities.

    FX P&L on securities = how much you gained/lost due to exchange rate changes.
    - Realized: On sold positions, (sale_rate - avg_purchase_rate) × foreign_proceeds
    - Unrealized: On current holdings, (current_rate - avg_purchase_rate) × current_foreign_value

    Returns a DataFrame with columns:
        currency, cash_holdings, realized_cash_pl, unrealized_cash_pl,
        realized_securities_pl, unrealized_securities_pl, total_realized_pl, total_unrealized_pl
    """
    from kodak.shared.market_data import get_exchange_rate, get_latest_prices

    # Get all transactions, using instrument currency for securities
    # Note: t.currency is settlement currency, i.currency is trading currency
    query = f"""
        SELECT
            t.date, t.type, t.instrument_id, t.quantity, t.amount, t.currency,
            t.exchange_rate, t.amount_local, i.symbol,
            COALESCE(i.currency, t.currency) as effective_currency
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        ORDER BY t.date, t.id
    """

    with get_db_connection() as conn:
        df = query_df(query, conn)

    if df.empty:
        return pd.DataFrame()

    # Track state per currency (for cash - only non-security transactions)
    currency_state = {}  # currency -> {cash_holdings, cash_cost, cash_realized_pl}

    # Track state per instrument (for securities FX P&L)
    # We need: qty, foreign_cost_basis, local_cost_basis to compute avg_purchase_rate
    instrument_state = {}  # instrument_id -> {qty, foreign_cost, local_cost, currency, realized_fx_pl}

    for _, row in df.iterrows():
        txn_currency = row['currency']  # Settlement currency
        effective_currency = row['effective_currency']  # Instrument currency or txn currency
        inst_id = row['instrument_id']
        amount = row['amount']
        amount_local = row['amount_local']
        exchange_rate = row['exchange_rate'] if pd.notna(row['exchange_rate']) else 1.0
        t_type = row['type']
        qty = row['quantity'] if pd.notna(row['quantity']) else 0

        # --- Handle securities (BUY/SELL) ---
        if pd.notna(inst_id) and t_type in ['BUY', 'SELL']:
            # Use instrument's currency for FX exposure
            security_currency = effective_currency

            # Skip if security is in base currency (no FX exposure)
            if security_currency == BASE_CURRENCY:
                continue

            if inst_id not in instrument_state:
                instrument_state[inst_id] = {
                    'qty': 0.0,
                    'foreign_cost': 0.0,
                    'local_cost': 0.0,
                    'currency': security_currency,
                    'realized_fx_pl': 0.0,
                    'symbol': row['symbol']
                }
            ist = instrument_state[inst_id]

            # Derive foreign amount from local amount and exchange rate
            # If exchange_rate is stored, foreign = local / rate
            # If txn_currency == security_currency, amount is already in foreign currency
            if txn_currency == security_currency:
                foreign_amount = abs(amount)
            elif exchange_rate > 0:
                foreign_amount = abs(amount_local) / exchange_rate
            else:
                foreign_amount = abs(amount_local)  # Fallback

            local_amount = abs(amount_local)

            if t_type == 'BUY':
                ist['qty'] += qty
                ist['foreign_cost'] += foreign_amount
                ist['local_cost'] += local_amount

            elif t_type == 'SELL' and ist['qty'] > 0:
                # Calculate avg purchase rate
                avg_purchase_rate = ist['local_cost'] / ist['foreign_cost'] if ist['foreign_cost'] > 0 else exchange_rate

                # FX P&L = foreign_proceeds × (sale_rate - avg_purchase_rate)
                fx_pl = foreign_amount * (exchange_rate - avg_purchase_rate)
                ist['realized_fx_pl'] += fx_pl

                # Reduce cost basis proportionally
                portion = min(abs(qty) / ist['qty'], 1.0)
                ist['qty'] += qty  # qty is negative for SELL
                ist['foreign_cost'] -= ist['foreign_cost'] * portion
                ist['local_cost'] -= ist['local_cost'] * portion

                if abs(ist['qty']) < 0.001:
                    ist['qty'] = 0
                    ist['foreign_cost'] = 0
                    ist['local_cost'] = 0

        # --- Handle cash flows (non-security transactions only) ---
        elif pd.isna(inst_id) and txn_currency != BASE_CURRENCY:
            if txn_currency not in currency_state:
                currency_state[txn_currency] = {
                    'cash_holdings': 0.0,
                    'cash_cost': 0.0,
                    'cash_realized_pl': 0.0
                }
            cs = currency_state[txn_currency]

            if amount > 0:
                cs['cash_holdings'] += amount
                cs['cash_cost'] += abs(amount_local)
            elif amount < 0:
                if cs['cash_holdings'] > 0:
                    portion = min(abs(amount) / cs['cash_holdings'], 1.0)
                    cost_portion = cs['cash_cost'] * portion
                    proceeds_local = abs(amount_local)
                    cs['cash_realized_pl'] += proceeds_local - cost_portion
                    cs['cash_cost'] -= cost_portion
                cs['cash_holdings'] += amount

                if abs(cs['cash_holdings']) < 0.01:
                    cs['cash_holdings'] = 0
                    cs['cash_cost'] = 0

    # --- Calculate unrealized FX P&L for current holdings ---
    holdings_df = get_holdings()
    inst_currency_map = {}
    prices = {}

    if not holdings_df.empty:
        with get_db_connection() as conn:
            inst_currencies = query_df("SELECT id, currency FROM instruments", conn)
        inst_currency_map = dict(zip(inst_currencies['id'], inst_currencies['currency']))
        prices = get_latest_prices(holdings_df['instrument_id'].tolist())

    # Build results per currency
    all_currencies = set(currency_state.keys())
    for ist in instrument_state.values():
        all_currencies.add(ist['currency'])

    results = []
    for currency in sorted(all_currencies):
        cs = currency_state.get(currency, {'cash_holdings': 0, 'cash_cost': 0, 'cash_realized_pl': 0})
        current_rate = get_exchange_rate(currency, BASE_CURRENCY)

        # Realized FX P&L from securities
        realized_securities_pl = sum(
            ist['realized_fx_pl'] for ist in instrument_state.values() if ist['currency'] == currency
        )

        # Unrealized FX P&L from current holdings
        unrealized_securities_pl = 0.0
        if not holdings_df.empty:
            for _, h_row in holdings_df.iterrows():
                inst_id = h_row['instrument_id']
                if inst_currency_map.get(inst_id) != currency:
                    continue
                if inst_id not in instrument_state:
                    continue

                ist = instrument_state[inst_id]
                if ist['qty'] <= 0 or ist['foreign_cost'] <= 0:
                    continue

                # Get current market value in foreign currency
                price_info = prices.get(inst_id)
                if price_info:
                    current_price, _ = price_info
                    current_foreign_value = h_row['quantity'] * current_price
                    avg_purchase_rate = ist['local_cost'] / ist['foreign_cost']

                    # Unrealized FX P&L = current_foreign_value × (current_rate - avg_purchase_rate)
                    unrealized_securities_pl += current_foreign_value * (current_rate - avg_purchase_rate)

        # Unrealized cash P&L
        unrealized_cash_pl = 0.0
        if cs['cash_holdings'] > 1.0 and cs['cash_cost'] > 0:
            current_value = cs['cash_holdings'] * current_rate
            unrealized_cash_pl = current_value - cs['cash_cost']

        results.append({
            'currency': currency,
            'cash_holdings': cs['cash_holdings'],
            'realized_cash_pl': cs['cash_realized_pl'],
            'unrealized_cash_pl': unrealized_cash_pl,
            'realized_securities_pl': realized_securities_pl,
            'unrealized_securities_pl': unrealized_securities_pl,
            'total_realized_pl': cs['cash_realized_pl'] + realized_securities_pl,
            'total_unrealized_pl': unrealized_cash_pl + unrealized_securities_pl
        })

    return pd.DataFrame(results)


def get_realized_performance():
    """
    Replays the ledger to calculate Realized Gains, Dividends, Fees, etc. by Year.
    Returns a DataFrame: year | realized_gl | dividends | interest | fees | tax | total_pl
    """
    # Get all transactions sorted by date
    query = '''
        SELECT
            t.date, t.type, t.instrument_id, t.quantity, t.amount_local,
            t.fee_local, i.symbol
        FROM transactions t
        LEFT JOIN instruments i ON t.instrument_id = i.id
        ORDER BY t.date, t.id
    '''
    with get_db_connection() as conn:
        df = query_df(query, conn)

    if df.empty:
        return pd.DataFrame()

    # State
    holdings = {} # inst_id -> {qty, total_cost}
    yearly = {}   # year -> {realized_gl, dividends, interest, fees, tax}

    def get_year(date_str):
        return str(date_str)[:4]

    def add_stat(year, category, value):
        if year not in yearly:
            yearly[year] = {'realized_gl': 0.0, 'dividends': 0.0, 'interest': 0.0, 'fees': 0.0, 'tax': 0.0}
        yearly[year][category] += value

    # Replay
    for _, row in df.iterrows():
        year = get_year(row['date'])
        t_type = row['type']
        inst_id = row['instrument_id']
        qty = row['quantity']
        amt = row['amount_local']
        fee = row['fee_local'] if pd.notna(row['fee_local']) else 0.0

        # Always track fees
        if fee > 0:
            add_stat(year, 'fees', -abs(fee)) # fees are negative impact

        # 1. Income / Costs
        if t_type == 'DIVIDEND':
            add_stat(year, 'dividends', amt)
        elif t_type == 'INTEREST':
            add_stat(year, 'interest', amt) # usually negative
        elif t_type == 'TAX':
            add_stat(year, 'tax', amt)      # usually negative
        elif t_type == 'FEE':
            add_stat(year, 'fees', -abs(amt)) # Explicit fee transaction

        # 2. Capital Gains (Buy/Sell)
        # Only process if instrument is involved
        if inst_id:
            if inst_id not in holdings:
                holdings[inst_id] = {'qty': 0.0, 'cost': 0.0}

            h = holdings[inst_id]

            # Identify Buy vs Sell using logic similar to get_holdings
            
            # Special handling for Splits (BYTTE)
            if t_type == 'BYTTE UTTAK VP':
                # Remove Quantity, KEEP Cost (deferred to new shares)
                h['qty'] += qty # negative
                continue
            
            if t_type == 'BYTTE INNLEGG VP':
                # Add Quantity, Add any extra cost (usually 0)
                h['qty'] += qty
                h['cost'] += abs(amt)
                continue

            # INFLOW (Buy)
            if t_type in ['BUY', 'DEPOSIT', 'TRANSFER_IN', 'TILDELING INNLEGG RE', 'EMISJON INNLEGG VP']:
                # Add to inventory
                h['qty'] += qty
                # Cost increases by amount paid (usually negative amount, so we take abs)
                cost_added = abs(amt)
                h['cost'] += cost_added

            # OUTFLOW (Sell)
            elif t_type in ['SELL', 'WITHDRAWAL', 'TRANSFER_OUT', 'INNLØSN. UTTAK VP']:
                # Calculate Realized Gain
                # Avg Cost Basis
                if h['qty'] > 0:
                    avg_cost = h['cost'] / h['qty']
                    cost_of_sold = avg_cost * abs(qty)

                    # Proceeds = Amount received (positive for sell)
                    proceeds = abs(amt)

                    # Gain = Proceeds - Cost
                    if t_type in ['SELL', 'INNLØSN. UTTAK VP', 'BYTTE UTTAK VP']:
                        gain = proceeds - cost_of_sold
                        add_stat(year, 'realized_gl', gain)

                    # Reduce Inventory
                    h['cost'] -= cost_of_sold

                h['qty'] += qty # qty is negative

                # Cleanup dust
                if abs(h['qty']) < 0.001:
                    h['qty'] = 0.0
                    h['cost'] = 0.0

    # Convert to DataFrame
    data = []
    for year, stats in yearly.items():
        row = stats.copy()
        row['year'] = year
        row['total_pl'] = sum(stats.values())
        data.append(row)

    if not data:
        return pd.DataFrame()
        
    return pd.DataFrame(data).sort_values('year')
