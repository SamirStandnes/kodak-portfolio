import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local,
    display_table, number_col, text_col, apply_plotly_theme,
)
from kodak.shared.calculations import get_dividend_details, get_dividend_forecast

page_setup("Dividend Analysis", "💰")


@st.cache_data(ttl=CACHE_TTL)
def load_dividend_data():
    return get_dividend_details()


@st.cache_data(ttl=CACHE_TTL)
def load_dividend_forecast():
    return get_dividend_forecast()


df_yearly, df_current_year, df_all_time = load_dividend_data()

# --- KEY METRICS ---
total_divs = df_yearly['total'].sum() if not df_yearly.empty else 0
current_year_total = df_current_year['total'].sum() if not df_current_year.empty else 0

col1, col2, col3 = st.columns(3)
col1.metric("All-Time Dividends", format_local(total_divs))
col2.metric("Current Year", format_local(current_year_total))
col3.metric("Paying Stocks", len(df_all_time) if not df_all_time.empty else 0)

st.divider()

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["Yearly Overview", "Top Payers", "Forecast"])

with tab1:
    if not df_yearly.empty:
        fig = px.bar(
            df_yearly, x='year', y='total',
            labels={'total': BASE_CURRENCY, 'year': ''},
            color_discrete_sequence=[COLORS['positive']],
        )
        fig.update_traces(
            name=BASE_CURRENCY,
            hovertemplate=f"<b>%{{x}}</b><br>%{{y:,.0f}} {BASE_CURRENCY}<extra></extra>",
        )
        apply_plotly_theme(fig)
        fig.update_layout(
            showlegend=False, hovermode='closest',
            xaxis_title='', yaxis_title=BASE_CURRENCY,
        )
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    tcol1, tcol2 = st.columns(2)
    with tcol1:
        st.caption("Current Year")
        display_table(df_current_year, {
            "symbol": text_col("Instrument"),
            "total": number_col(f"Total ({BASE_CURRENCY})"),
        }, height=350)
    with tcol2:
        st.caption("All Time (Top 30)")
        display_table(df_all_time.head(30), {
            "symbol": text_col("Instrument"),
            "total": number_col(f"Total ({BASE_CURRENCY})"),
        }, height=350)

with tab3:
    with st.spinner("Fetching dividend forecast..."):
        df_forecast, forecast_summary = load_dividend_forecast()

    if not df_forecast.empty:
        st.metric("Estimated Annual Dividends", f"{forecast_summary['total_estimate_local']:,.0f} {BASE_CURRENCY}")

        df_display = df_forecast.sort_values('annual_estimate_local', ascending=False)
        display_table(df_display, {
            "symbol": text_col("Symbol"),
            "quantity": number_col("Shares", fmt="%d"),
            "dividend_per_share": number_col("Div/Share", fmt="%.2f"),
            "currency": text_col("Currency"),
            "annual_estimate": number_col("Annual Est.", fmt="%d"),
            "annual_estimate_local": number_col(f"Est. ({BASE_CURRENCY})", fmt="%d"),
            "source": text_col("Source"),
        }, height=400)

        st.caption(
            f"**yahoo** = Forward dividend rate | **ttm** = Trailing 12-month history | "
            f"Coverage: {forecast_summary['yahoo_count']} yahoo, {forecast_summary['ttm_count']} ttm, "
            f"{forecast_summary['no_data_count']} no data"
        )
    else:
        st.info("No dividend-paying holdings found.")
