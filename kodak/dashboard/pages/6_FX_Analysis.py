import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup, format_local,
    display_table, number_col, text_col,
)
from kodak.shared.calculations import get_fx_performance_detailed

page_setup("Currency Performance", "💱")


@st.cache_data(ttl=CACHE_TTL)
def load_fx_data():
    return get_fx_performance_detailed()


df = load_fx_data()

if df.empty:
    st.info("No foreign currency exposure found.")
else:
    total_realized = df['total_realized_pl'].sum()
    total_unrealized = df['total_unrealized_pl'].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Realized FX P&L", format_local(total_realized))
    col2.metric("Unrealized FX P&L", format_local(total_unrealized))
    col3.metric("Total FX P&L", format_local(total_realized + total_unrealized))

    st.divider()

    st.subheader("FX P&L by Currency")

    display_df = df[[
        'currency', 'realized_cash_pl', 'realized_securities_pl',
        'total_realized_pl', 'unrealized_securities_pl', 'total_unrealized_pl',
    ]].copy()
    display_df['total_fx_pl'] = display_df['total_realized_pl'] + display_df['total_unrealized_pl']

    display_table(display_df, {
        "currency": text_col("Currency"),
        "realized_cash_pl": number_col(f"Cash P&L ({BASE_CURRENCY})",
                                       help="Realized FX gains/losses from currency exchange transactions"),
        "realized_securities_pl": number_col("Securities P&L (Realized)",
                                             help="FX gains/losses realized when selling foreign securities"),
        "total_realized_pl": number_col("Total Realized"),
        "unrealized_securities_pl": number_col("Securities P&L (Unrealized)",
                                               help="FX gains/losses on current holdings due to rate changes"),
        "total_unrealized_pl": number_col("Total Unrealized"),
        "total_fx_pl": number_col(f"Total FX P&L ({BASE_CURRENCY})"),
    }, height=300)

    st.divider()
    st.caption("""
    **How FX P&L is calculated:**
    - **Cash P&L**: Gains/losses from explicit currency exchange transactions
    - **Securities P&L (Realized)**: When you sell a foreign stock, FX P&L = proceeds x (sale rate - avg purchase rate)
    - **Securities P&L (Unrealized)**: For current holdings, FX P&L = current value x (current rate - avg purchase rate)
    """)
