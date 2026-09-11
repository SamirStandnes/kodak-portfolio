import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup, format_local, display_aggrid,
)
from kodak.shared.db import get_db_connection, query_df

page_setup("Portfolio Activity", "📝", "The complete transaction ledger, filterable and exportable.")


@st.cache_data(ttl=CACHE_TTL)
def load_all_transactions() -> pd.DataFrame:
    """The full ledger (a few thousand rows) — filtered client-side below."""
    with get_db_connection() as conn:
        df = query_df("""
            SELECT t.date, a.name as account, t.type,
                   COALESCE(i.symbol, i.isin) as symbol,
                   t.quantity, t.price, t.amount, t.currency,
                   t.amount_local, t.fee_local, t.batch_id, t.source_file,
                   t.notes as description
            FROM transactions t
            JOIN accounts a ON t.account_id = a.id
            LEFT JOIN instruments i ON t.instrument_id = i.id
            ORDER BY t.date DESC, t.id DESC
        """, conn)
    df['date'] = df['date'].astype(str).str[:10]
    return df


df_all = load_all_transactions()

if df_all.empty:
    st.info("No transactions in the database yet.")
    st.stop()

# --- FILTERS ---
with st.container(border=True):
    f1, f2, f3 = st.columns([2, 2, 2])
    accounts = f1.multiselect("Account", sorted(df_all['account'].dropna().unique()), placeholder="All accounts")
    types = f2.multiselect("Type", sorted(df_all['type'].dropna().unique()), placeholder="All types")
    symbol_query = f3.text_input("Instrument contains", placeholder="e.g. MSFT or NO001")

    f4, f5, f6 = st.columns([2, 2, 2])
    min_date = pd.to_datetime(df_all['date'].min()).date()
    max_date = pd.to_datetime(df_all['date'].max()).date()
    date_range = f4.date_input("Date range", (min_date, max_date), min_value=min_date, max_value=max_date)
    text_query = f5.text_input("Notes / source contains", placeholder="free text")
    limit = f6.select_slider("Rows to show", options=[50, 100, 250, 500, 1000, "All"], value=100)

df = df_all
if accounts:
    df = df[df['account'].isin(accounts)]
if types:
    df = df[df['type'].isin(types)]
if symbol_query:
    df = df[df['symbol'].fillna('').str.contains(symbol_query.strip(), case=False, regex=False)]
if text_query:
    q = text_query.strip()
    df = df[df['description'].fillna('').str.contains(q, case=False, regex=False)
            | df['source_file'].fillna('').str.contains(q, case=False, regex=False)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = (d.isoformat() for d in date_range)
    df = df[(df['date'] >= start) & (df['date'] <= end)]

matched = len(df)
if limit != "All":
    df = df.head(int(limit))

# --- SUMMARY ---
received = df.loc[df['amount_local'] > 0, 'amount_local'].sum()
paid = df.loc[df['amount_local'] < 0, 'amount_local'].sum()
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Matching Transactions", matched, help=f"Showing {len(df)}")
s2.metric(f"Received ({BASE_CURRENCY})", format_local(received),
          help="Sum of positive amounts in the rows shown: sale proceeds, deposits, dividends, interest received")
s3.metric(f"Paid ({BASE_CURRENCY})", format_local(paid),
          help="Sum of negative amounts in the rows shown: purchases, withdrawals, fees, interest charged")
s4.metric(f"Net ({BASE_CURRENCY})", format_local(received + paid),
          help="Received + Paid. Filtered to one direction (e.g. only sells) this is simply that total.")
s5.metric(f"Fees ({BASE_CURRENCY})", format_local(df['fee_local'].fillna(0).sum()),
          help="Trading fees embedded in the rows shown")
st.download_button(
    "Download CSV", df.to_csv(index=False).encode('utf-8'),
    file_name="kodak_transactions.csv", mime="text/csv",
)

order = ["date", "account", "type", "symbol", "quantity", "price", "amount", "currency",
         "amount_local", "fee_local", "description", "batch_id", "source_file"]
display_aggrid(df[order], columns={
    "date":         {"label": "Date", "width": 100},
    "account":      {"label": "Account", "width": 120},
    "type":         {"label": "Type", "width": 150},
    "symbol":       {"label": "Instrument", "width": 105},
    "quantity":     {"label": "Qty", "type": "quantity", "decimals": 4, "width": 80},
    "price":        {"label": "Price", "type": "number", "decimals": 2, "width": 90},
    "amount":       {"label": "Amount", "type": "number", "decimals": 2, "width": 105},
    "currency":     {"label": "Ccy", "width": 60},
    "amount_local": {"label": f"Amount ({BASE_CURRENCY})", "type": "currency", "decimals": 0, "color_signed": True, "width": 115},
    "fee_local":    {"label": "Fee", "type": "number", "decimals": 2, "width": 80},
    "description":  {"label": "Notes", "width": 220},
    "batch_id":     {"label": "Batch", "width": 130},
    "source_file":  {"label": "Source", "width": 160},
}, pin_left=["date"], height=min(640, 34 * len(df) + 36 + 4))
