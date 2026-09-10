import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import os
from datetime import date

import streamlit as st
import pandas as pd
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup, display_table, text_col, number_col,
    load_valued_holdings,
)
from kodak.shared.db import get_db_connection, query_df

page_setup("System Status", "⚙️")

IS_CLOUD = bool(os.environ.get("DATABASE_URL"))

# --- Config ---
st.subheader("Configuration")
c1, c2, c3 = st.columns(3)
c1.metric("Base Currency", BASE_CURRENCY)
c2.metric("Database", "PostgreSQL (Neon)" if IS_CLOUD else "SQLite (local)")
c3.metric("Cache TTL", f"{CACHE_TTL // 60} min")

# --- Market data freshness ---
st.subheader("Market Data Freshness")


@st.cache_data(ttl=CACHE_TTL)
def load_freshness():
    with get_db_connection() as conn:
        prices = query_df(
            "SELECT MAX(date) as latest, COUNT(DISTINCT instrument_id) as instruments, COUNT(*) as rows_ "
            "FROM market_prices", conn)
        fx = query_df(
            "SELECT from_currency, MAX(date) as latest, COUNT(*) as rows_ FROM exchange_rates "
            "WHERE to_currency = ? GROUP BY from_currency ORDER BY from_currency",
            conn, params=(BASE_CURRENCY,))
        staging = query_df("SELECT COUNT(*) as n FROM transactions_staging", conn).iloc[0]['n']
    return prices.iloc[0].to_dict(), fx, int(staging)


price_info, df_fx, staging_rows = load_freshness()
df_val = load_valued_holdings()
held = len(df_val)
unpriced = df_val[~df_val['has_price']] if not df_val.empty else pd.DataFrame()

latest = price_info.get('latest')
priced_on_latest = int((df_val['price_date'].astype(str) == str(latest)[:10]).sum()) if not df_val.empty else 0
age_days = (date.today() - date.fromisoformat(str(latest)[:10])).days if latest else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Latest Price Date", str(latest)[:10] if latest else "—",
          delta=f"{age_days} day(s) old" if age_days is not None else None,
          delta_color="inverse" if (age_days or 0) > 3 else "off")
m2.metric("Priced on Latest Date", f"{priced_on_latest} / {held}",
          help="Held instruments that have a close stored for the latest price date")
m3.metric("Held Without Any Price", len(unpriced))
m4.metric("Staged (uncommitted)", staging_rows,
          help="Rows waiting in transactions_staging for review")

if age_days is not None and age_days > 3:
    st.warning(
        f"Prices are {age_days} days old. Run `.\\workflows\\refresh_market_data.ps1` locally "
        "(the cloud cron refreshes weekdays at 22:00 UTC)."
    )
if not unpriced.empty:
    with st.expander(f"{len(unpriced)} held instrument(s) have no stored price — carried at cost"):
        display_table(unpriced[['symbol', 'name', 'quantity', 'cost_basis_local']].rename(columns={
            'symbol': 'Symbol', 'name': 'Name', 'quantity': 'Quantity', 'cost_basis_local': f'Cost ({BASE_CURRENCY})',
        }), {
            "Quantity": number_col("Quantity", fmt="%.2f"),
            f"Cost ({BASE_CURRENCY})": number_col(f"Cost ({BASE_CURRENCY})"),
        }, height=min(300, 40 * len(unpriced) + 60))
        st.caption("Usually a missing or wrong Yahoo symbol in `data/reference/isin_map.csv`, "
                   "or an unlisted instrument (rights, private company).")

if not df_fx.empty:
    st.caption(f"Exchange rates to {BASE_CURRENCY}")
    display_table(df_fx.rename(columns={'from_currency': 'Currency', 'latest': 'Latest Rate Date', 'rows_': 'Stored Rates'}), {
        "Stored Rates": number_col("Stored Rates"),
    }, height=min(300, 40 * len(df_fx) + 60))

# --- Data Freshness ---
st.subheader("Data Source Status")


@st.cache_data(ttl=CACHE_TTL)
def get_data_freshness():
    with get_db_connection() as conn:
        return query_df('''
            SELECT source_file as "Source",
                   MAX(date) as "Last Transaction Date",
                   COUNT(*) as "Total Transactions"
            FROM transactions
            GROUP BY source_file
            ORDER BY MAX(date) DESC
        ''', conn)


df_freshness = get_data_freshness()

if not df_freshness.empty:
    display_table(df_freshness, {
        "Source": text_col("Source File / Account"),
        "Last Transaction Date": st.column_config.DateColumn("Latest Data", format="YYYY-MM-DD"),
        "Total Transactions": number_col("Record Count"),
    }, height=300)
else:
    st.warning("No transactions found in the database.")

# --- DB Stats ---
with st.expander("Database Statistics"):
    try:
        with get_db_connection() as conn:
            tables = query_df("SELECT name FROM sqlite_master WHERE type='table';", conn)
            stats = []
            for table in tables['name']:
                if table.startswith('sqlite_'):
                    continue
                count = query_df(f"SELECT COUNT(*) as c FROM {table}", conn).iloc[0]['c']
                stats.append({'Table': table, 'Rows': int(count)})

        display_table(pd.DataFrame(stats), {
            "Table": text_col("Table"),
            "Rows": number_col("Rows"),
        }, height=250)
    except Exception as e:
        st.error(f"Error fetching stats: {e}")

if st.button("Refresh System & Clear Cache"):
    st.cache_data.clear()
    st.rerun()
