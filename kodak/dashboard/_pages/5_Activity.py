import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup, format_local,
    display_table, number_col, text_col, date_col,
)
from kodak.shared.db import get_db_connection, query_df

page_setup("Portfolio Activity", "📝")


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
s1, s2, s3, s4 = st.columns(4)
s1.metric("Matching Transactions", matched, help=f"Showing {len(df)}")
s2.metric(f"Net Cash Flow ({BASE_CURRENCY})", format_local(df['amount_local'].sum()),
          help="Sum of amount in base currency over the rows shown")
s3.metric(f"Fees ({BASE_CURRENCY})", format_local(df['fee_local'].fillna(0).sum()))
s4.download_button(
    "Download CSV", df.to_csv(index=False).encode('utf-8'),
    file_name="kodak_transactions.csv", mime="text/csv", width="stretch",
)

display_table(df, {
    "date": date_col(),
    "account": text_col("Account"),
    "type": text_col("Type"),
    "symbol": text_col("Instrument"),
    "quantity": number_col("Qty", fmt="%.4f"),
    "price": number_col("Price", fmt="%.2f"),
    "amount": number_col("Amount", fmt="%.2f"),
    "currency": text_col("Curr"),
    "amount_local": number_col(f"Amount ({BASE_CURRENCY})"),
    "fee_local": number_col(f"Fee ({BASE_CURRENCY})", fmt="%.2f"),
    "batch_id": text_col("Batch ID"),
    "source_file": text_col("Source"),
    "description": text_col("Notes"),
})
