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
from kodak.shared.calculations import get_fee_details, get_fee_analysis, get_platform_fees

page_setup("Fee Analysis", "💸")


@st.cache_data(ttl=CACHE_TTL)
def load_fee_data():
    return get_fee_details()


df_yearly, df_currency, df_top = load_fee_data()

total_fees = df_yearly['total'].sum()
st.metric("Total Fees Paid (All Time)", format_local(total_fees))

col1, col2 = st.columns(2)

with col1:
    st.subheader("Fees by Year")
    if not df_yearly.empty:
        fig = px.bar(df_yearly, x='year', y='total', color_discrete_sequence=[COLORS['warning']])
        fig.update_layout(xaxis_title="", yaxis_title=BASE_CURRENCY, showlegend=False)
        apply_plotly_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Fees by Currency")
    display_table(df_currency, {
        "currency": text_col("Currency"),
        "total": number_col(f"Total Fees ({BASE_CURRENCY})"),
    }, height=250)

st.divider()
st.subheader("Recent Individual Fees")
display_table(df_top, {
    "date": date_col(),
    "currency": text_col("Fee Currency"),
    "amount_local": number_col(f"Fee ({BASE_CURRENCY})"),
    "source_file": text_col("Source"),
}, height=300)

st.divider()
st.subheader("Fee Efficiency by Broker")
st.caption(f"Cost per 100 {BASE_CURRENCY} traded (lower is better)")

df_broker = get_fee_analysis()
if not df_broker.empty:
    col1, col2 = st.columns([2, 1])

    with col1:
        display_table(df_broker, {
            "broker": text_col("Broker"),
            "total_traded": number_col(f"Total Traded ({BASE_CURRENCY})"),
            "total_fees": number_col(f"Total Fees ({BASE_CURRENCY})"),
            "fee_per_100": number_col(f"Fee per 100 {BASE_CURRENCY}", fmt="%.4f"),
            "num_trades": number_col("# Trades"),
        }, height=250)

    with col2:
        fig = px.bar(df_broker, x='broker', y='fee_per_100',
                     color_discrete_sequence=[COLORS['negative']])
        fig.update_layout(xaxis_title="", yaxis_title=f"Fee per 100 {BASE_CURRENCY}", showlegend=False)
        apply_plotly_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trading data available for fee analysis.")

st.divider()
st.subheader("Platform & Custody Fees by Broker")
st.caption("Monthly subscription/custody fees (not per-trade)")

df_platform = get_platform_fees()
if not df_platform.empty:
    col1, col2 = st.columns([2, 1])

    with col1:
        display_table(df_platform, {
            "broker": text_col("Broker"),
            "total_fees": number_col(f"Total Fees ({BASE_CURRENCY})"),
            "monthly_avg": number_col(f"Avg Monthly ({BASE_CURRENCY})", fmt="%.2f"),
            "num_charges": number_col("# Charges"),
        }, height=250)

    with col2:
        fig = px.bar(df_platform, x='broker', y='monthly_avg',
                     color_discrete_sequence=[COLORS['purple']])
        fig.update_layout(xaxis_title="", yaxis_title=f"Monthly Avg ({BASE_CURRENCY})", showlegend=False)
        apply_plotly_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No platform fee data available.")
