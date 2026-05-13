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

# --- KEY METRICS ---
total_fees = df_yearly['total'].sum() if not df_yearly.empty else 0

col1, col2 = st.columns(2)
col1.metric("Total Fees Paid (All Time)", format_local(total_fees))
col2.metric("Fee Currencies", len(df_currency) if not df_currency.empty else 0)

st.divider()

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["Yearly Overview", "Broker Efficiency", "Recent Fees"])

with tab1:
    tcol1, tcol2 = st.columns([2, 1])
    with tcol1:
        if not df_yearly.empty:
            fig = px.bar(
                df_yearly, x='year', y='total',
                labels={'total': BASE_CURRENCY, 'year': ''},
                color_discrete_sequence=[COLORS['warning']],
            )
            fig.update_traces(
                name=BASE_CURRENCY,
                hovertemplate=f"<b>%{{x}}</b><br>%{{y:,.0f}} {BASE_CURRENCY}<extra></extra>",
            )
            apply_plotly_theme(fig)
            fig.update_layout(showlegend=False, hovermode='closest')
            st.plotly_chart(fig, use_container_width=True)
    with tcol2:
        st.caption("By Currency")
        display_table(df_currency, {
            "currency": text_col("Currency"),
            "total": number_col(f"Total ({BASE_CURRENCY})"),
        }, height=250)

with tab2:
    st.caption(f"Trading fees — cost per 100 {BASE_CURRENCY} traded (lower is better)")
    df_broker = get_fee_analysis()
    if not df_broker.empty:
        display_table(df_broker, {
            "broker": text_col("Broker"),
            "total_traded": number_col(f"Total Traded ({BASE_CURRENCY})"),
            "total_fees": number_col(f"Total Fees ({BASE_CURRENCY})"),
            "fee_per_100": number_col(f"Fee/100 {BASE_CURRENCY}", fmt="%.4f"),
            "num_trades": number_col("# Trades"),
        }, height=250)
    else:
        st.info("No trading data available.")

    st.divider()
    st.caption("Platform & custody fees (monthly)")
    df_platform = get_platform_fees()
    if not df_platform.empty:
        display_table(df_platform, {
            "broker": text_col("Broker"),
            "total_fees": number_col(f"Total ({BASE_CURRENCY})"),
            "monthly_avg": number_col(f"Avg Monthly ({BASE_CURRENCY})", fmt="%.2f"),
            "num_charges": number_col("# Charges"),
        }, height=250)
    else:
        st.info("No platform fee data available.")

with tab3:
    display_table(df_top, {
        "date": date_col(),
        "currency": text_col("Fee Currency"),
        "amount_local": number_col(f"Fee ({BASE_CURRENCY})"),
        "source_file": text_col("Source"),
    }, height=400)
