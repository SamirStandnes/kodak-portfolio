import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup,
    display_table, number_col, text_col, date_col,
)
from kodak.shared.db import get_connection, query_df

page_setup("Portfolio Activity", "📝")

# --- CONTROLS ---
col1, col2 = st.columns([2, 1])

with col1:
    show_all = st.checkbox("Show All Transactions")
    num_txns = st.slider("Number of transactions to show", 10, 500, 50, disabled=show_all)


@st.cache_data(ttl=CACHE_TTL)
def load_activity_data(limit, all_txns):
    conn = get_connection()
    query = """
        SELECT t.date, a.name as account, t.type,
               COALESCE(i.symbol, i.isin) as symbol,
               t.quantity, t.price, t.amount, t.currency,
               t.amount_local, t.batch_id, t.source_file,
               t.notes as description
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        LEFT JOIN instruments i ON t.instrument_id = i.id
        ORDER BY t.date DESC, t.id DESC
    """
    if not all_txns:
        query += f" LIMIT {limit}"

    df = query_df(query, conn)
    conn.close()
    return df


df = load_activity_data(num_txns, show_all)

st.metric("Transactions Displayed", len(df))

display_table(df, {
    "date": date_col(),
    "account": text_col("Account"),
    "type": text_col("Type"),
    "symbol": text_col("Instrument"),
    "quantity": number_col("Qty"),
    "price": number_col("Price"),
    "amount": number_col("Amount"),
    "currency": text_col("Curr"),
    "amount_local": number_col(f"Amount ({BASE_CURRENCY})"),
    "batch_id": text_col("Batch ID"),
    "source_file": text_col("Source"),
    "description": text_col("Notes"),
})
