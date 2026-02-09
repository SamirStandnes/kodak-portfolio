import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.shared.calculations import get_fx_performance_detailed
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, styled_subheader

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="FX Analysis", page_icon="💱", layout="wide")
apply_theme()

page_header("Currency Performance", "Foreign exchange impact on your portfolio")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_fx_data():
    return get_fx_performance_detailed()

df = load_fx_data()

if df.empty:
    st.info("No foreign currency exposure found.")
else:
    # Summary Metrics
    total_realized = df['total_realized_pl'].sum()
    total_unrealized = df['total_unrealized_pl'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Realized FX P&L", format_local(total_realized))
    col2.metric("Total Unrealized FX P&L", format_local(total_unrealized))
    col3.metric("Total FX P&L", format_local(total_realized + total_unrealized))

    st.divider()

    # Detailed breakdown
    styled_subheader("FX P&L by Currency")

    # Create display dataframe with better column names
    display_df = df[[
        'currency',
        'realized_cash_pl',
        'realized_securities_pl',
        'total_realized_pl',
        'unrealized_securities_pl',
        'total_unrealized_pl'
    ]].copy()

    # Add total column
    display_df['total_fx_pl'] = display_df['total_realized_pl'] + display_df['total_unrealized_pl']

    st.dataframe(
        display_df,
        column_config={
            "currency": st.column_config.TextColumn("Currency"),
            "realized_cash_pl": st.column_config.NumberColumn(
                f"Cash P&L ({BASE_CURRENCY})",
                format="localized",
                help="Realized FX gains/losses from currency exchange transactions"
            ),
            "realized_securities_pl": st.column_config.NumberColumn(
                "Securities P&L (Realized)",
                format="localized",
                help="FX gains/losses realized when selling foreign securities"
            ),
            "total_realized_pl": st.column_config.NumberColumn(
                "Total Realized",
                format="localized"
            ),
            "unrealized_securities_pl": st.column_config.NumberColumn(
                "Securities P&L (Unrealized)",
                format="localized",
                help="FX gains/losses on current holdings due to exchange rate changes"
            ),
            "total_unrealized_pl": st.column_config.NumberColumn(
                "Total Unrealized",
                format="localized"
            ),
            "total_fx_pl": st.column_config.NumberColumn(
                f"Total FX P&L ({BASE_CURRENCY})",
                format="localized"
            ),
        },
        use_container_width=True,
        hide_index=True
    )

    # Explanation
    st.divider()
    st.caption("""
    **How FX P&L is calculated:**
    - **Cash P&L**: Gains/losses from explicit currency exchange transactions
    - **Securities P&L (Realized)**: When you sell a foreign stock, FX P&L = proceeds x (sale rate - avg purchase rate)
    - **Securities P&L (Unrealized)**: For current holdings, FX P&L = current value x (current rate - avg purchase rate)
    """)
