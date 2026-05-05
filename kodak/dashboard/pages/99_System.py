import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.dashboard.common import BASE_CURRENCY, page_setup, display_table, text_col, number_col
from kodak.shared.db import get_connection, query_df

page_setup("System Status", "⚙️")

# --- Config ---
st.subheader("Configuration")
st.info(f"**Base Currency:** {BASE_CURRENCY}")

# --- Data Freshness ---
st.subheader("Data Source Status")


def get_data_freshness():
    conn = get_connection()
    query = '''
        SELECT source_file as "Source",
               MAX(date) as "Last Transaction Date",
               COUNT(*) as "Total Transactions"
        FROM transactions
        GROUP BY source_file
        ORDER BY MAX(date) DESC
    '''
    df = query_df(query, conn)
    conn.close()
    return df


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
    conn = get_connection()
    try:
        tables = query_df("SELECT name FROM sqlite_master WHERE type='table';", conn)
        stats = []
        for table in tables['name']:
            count = query_df(f"SELECT COUNT(*) as c FROM {table}", conn).iloc[0]['c']
            stats.append({'Table': table, 'Rows': count})

        display_table(pd.DataFrame(stats), {
            "Table": text_col("Table"),
            "Rows": number_col("Rows"),
        }, height=250)
    except Exception as e:
        st.error(f"Error fetching stats: {e}")
    finally:
        conn.close()

if st.button("Refresh System & Clear Cache"):
    st.cache_data.clear()
    st.rerun()
