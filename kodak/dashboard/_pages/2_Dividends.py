import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local, format_pct,
    display_table, number_col, text_col, render_chart, load_valued_holdings,
)
from kodak.shared.calculations import get_dividend_details, get_dividend_forecast, get_monthly_dividends

page_setup("Dividend Analysis", "💰")


@st.cache_data(ttl=CACHE_TTL)
def load_dividend_data():
    return get_dividend_details()


@st.cache_data(ttl=CACHE_TTL)
def load_dividend_forecast():
    return get_dividend_forecast()


@st.cache_data(ttl=CACHE_TTL)
def load_monthly_dividends(months: int):
    return get_monthly_dividends(months)


df_yearly, df_current_year, df_all_time = load_dividend_data()
df_monthly = load_monthly_dividends(24)

# --- KEY METRICS ---
total_divs = df_yearly['total'].sum() if not df_yearly.empty else 0
current_year_total = df_current_year['total'].sum() if not df_current_year.empty else 0
ttm_total = df_monthly.tail(12)['total'].sum() if not df_monthly.empty else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("All-Time Dividends", format_local(total_divs))
col2.metric("Current Year", format_local(current_year_total))
col3.metric("Trailing 12 Months", format_local(ttm_total))
col4.metric("Paying Stocks", len(df_all_time) if not df_all_time.empty else 0)

st.divider()

# --- TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["Yearly Overview", "Monthly", "Top Payers", "Forecast"])

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
        fig.update_layout(
            showlegend=False, hovermode='closest',
            xaxis_title='', yaxis_title=BASE_CURRENCY, xaxis=dict(type='category'),
        )
        render_chart(fig)
    else:
        st.info("No dividends recorded yet.")

with tab2:
    if df_monthly['total'].abs().sum() == 0:
        st.info("No dividends in the last 24 months.")
    else:
        fig_m = px.bar(
            df_monthly, x='month', y='total',
            labels={'total': BASE_CURRENCY, 'month': ''},
            color_discrete_sequence=[COLORS['positive']],
        )
        fig_m.update_traces(hovertemplate=f"<b>%{{x|%b %Y}}</b><br>%{{y:,.0f}} {BASE_CURRENCY}<extra></extra>")
        fig_m.update_layout(
            showlegend=False, hovermode='closest',
            xaxis_title='', yaxis_title=BASE_CURRENCY,
            xaxis=dict(tickformat='%b\n%Y', dtick='M2'),
        )
        render_chart(fig_m)
        avg = df_monthly.tail(12)['total'].mean()
        st.caption(f"Average over the last 12 months: **{format_local(avg)} {BASE_CURRENCY}/month**")

with tab3:
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

with tab4:
    with st.spinner("Fetching dividend forecast..."):
        df_forecast, forecast_summary = load_dividend_forecast()

    if not df_forecast.empty:
        df_val = load_valued_holdings()
        cost_basis = float(df_val['cost_basis_local'].sum()) if not df_val.empty else 0
        market_value = float(df_val['market_value_local'].sum()) if not df_val.empty else 0
        estimate = forecast_summary['total_estimate_local']

        f1, f2, f3 = st.columns(3)
        f1.metric("Estimated Annual Dividends", format_local(estimate))
        f2.metric("Yield on Cost", format_pct(estimate / cost_basis * 100 if cost_basis else 0, 2),
                  help="Estimated annual dividends ÷ cost basis of current holdings")
        f3.metric("Portfolio Yield", format_pct(estimate / market_value * 100 if market_value else 0, 2),
                  help="Estimated annual dividends ÷ current market value")

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
