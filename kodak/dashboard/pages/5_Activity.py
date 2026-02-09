import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.shared.db import get_connection
from kodak.shared.utils import load_config
from kodak.dashboard.style import apply_theme, page_header

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Activity", page_icon="📝", layout="wide")
apply_theme()

page_header("Portfolio Activity", "Full transaction history")

# --- CONTROLS ---
col1, col2 = st.columns([2, 1])

with col1:
    show_all = st.checkbox("Show All Transactions")
    num_txns = st.slider("Number of transactions to show", 10, 500, 50, disabled=show_all)

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_activity_data(limit, all_txns):
    conn = get_connection()

    query = """
        SELECT
            t.date,
            a.name as account,
            t.type,
            COALESCE(i.symbol, i.isin) as symbol,
            t.quantity,
            t.price,
            t.amount,
            t.currency,
            t.amount_local,
            t.batch_id,
            t.source_file,
            t.notes as description
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        LEFT JOIN instruments i ON t.instrument_id = i.id
        ORDER BY t.date DESC, t.id DESC
    """

    if not all_txns:
        query += f" LIMIT {limit}"

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

df = load_activity_data(num_txns, show_all)

# --- DISPLAY ---

# Metrics at the top
st.metric("Transactions Displayed", len(df))

# The Main Table
st.dataframe(
    df,
    column_config={
        "date": st.column_config.DateColumn("Date"),
        "account": st.column_config.TextColumn("Account"),
        "type": st.column_config.TextColumn("Type"),
        "symbol": st.column_config.TextColumn("Instrument"),
        "quantity": st.column_config.NumberColumn("Qty", format="localized"),
        "price": st.column_config.NumberColumn("Price", format="localized"),
        "amount": st.column_config.NumberColumn("Amount", format="localized"),
        "currency": st.column_config.TextColumn("Curr"),
        "amount_local": st.column_config.NumberColumn(f"Amount ({BASE_CURRENCY})", format="localized"),
        "batch_id": st.column_config.TextColumn("Batch ID"),
        "source_file": st.column_config.TextColumn("Source"),
        "description": st.column_config.TextColumn("Notes"),
    },
    use_container_width=True,
    hide_index=True,
    height=600
)
