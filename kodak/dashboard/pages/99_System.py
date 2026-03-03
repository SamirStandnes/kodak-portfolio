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
from kodak.dashboard.style import apply_theme, page_header, styled_subheader

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="System Status", page_icon="⚙️", layout="wide")
apply_theme()

page_header("System Status", "Configuration and data health")

# --- 1. System Config ---
styled_subheader("Configuration")
st.info(f"**Base Currency:** {BASE_CURRENCY}")

# --- 2. Data Freshness ---
styled_subheader("Data Source Status")

def get_data_freshness():
    conn = get_connection()

    # Check Transactions table
    query = """
        SELECT
            source_file as Source,
            MAX(date) as 'Last Transaction Date',
            COUNT(*) as 'Total Transactions'
        FROM transactions
        GROUP BY source_file
        ORDER BY MAX(date) DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

df_freshness = get_data_freshness()

if not df_freshness.empty:
    st.dataframe(
        df_freshness,
        column_config={
            "Source": st.column_config.TextColumn("Source File / Account"),
            "Last Transaction Date": st.column_config.DateColumn("Latest Data", format="YYYY-MM-DD"),
            "Total Transactions": st.column_config.NumberColumn("Record Count"),
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.warning("No transactions found in the database.")

# --- 3. Database Info (Optional) ---
with st.expander("Database Statistics"):
    conn = get_connection()
    try:
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)
        st.write("Tables in database:", tables['name'].tolist())

        # Row counts
        stats = []
        for table in tables['name']:
            count = pd.read_sql_query(f"SELECT COUNT(*) as c FROM {table}", conn).iloc[0]['c']
            stats.append({'Table': table, 'Rows': count})

        st.dataframe(pd.DataFrame(stats), hide_index=True)

    except Exception as e:
        st.error(f"Error fetching stats: {e}")
    finally:
        conn.close()

if st.button("Refresh System & Clear Cache"):
    st.cache_data.clear()
    st.rerun()
