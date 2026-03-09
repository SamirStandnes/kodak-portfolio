import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local,
    display_table, number_col, text_col, date_col, apply_plotly_theme,
)
from kodak.shared.calculations import get_interest_details

page_setup("Interest Analysis", "🏦")


@st.cache_data(ttl=CACHE_TTL)
def load_interest_data():
    return get_interest_details()


df_yearly, df_currency, df_top = load_interest_data()

total_interest = df_yearly['total'].sum()
st.metric("Total Interest Paid (All Time)", format_local(total_interest))

col1, col2 = st.columns(2)

with col1:
    st.subheader("Interest by Year")
    if not df_yearly.empty:
        fig = px.bar(df_yearly, x='year', y='total', color_discrete_sequence=[COLORS['primary']])
        fig.update_layout(xaxis_title="", yaxis_title=BASE_CURRENCY, showlegend=False)
        apply_plotly_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Interest by Currency")
    display_table(df_currency, {
        "currency": text_col("Currency"),
        "total": number_col(f"Total Interest ({BASE_CURRENCY})"),
    }, height=250)

st.subheader("Recent Interest Payments")
display_table(df_top, {
    "date": date_col(),
    "currency": text_col("Curr"),
    "amount": number_col("Amount (Orig)"),
    "amount_local": number_col(f"Amount ({BASE_CURRENCY})"),
    "source_file": text_col("Source"),
}, height=400)
