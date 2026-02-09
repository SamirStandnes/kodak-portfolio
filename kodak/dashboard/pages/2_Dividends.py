import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.shared.calculations import get_dividend_details, get_dividend_forecast
from kodak.shared.utils import load_config
from kodak.dashboard.style import apply_theme, page_header, styled_subheader, get_plotly_layout, COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Dividend Analysis", page_icon="💰", layout="wide")
apply_theme()

page_header("Dividend Analysis", "Income from your holdings")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_dividend_data():
    return get_dividend_details()

@st.cache_data(ttl=300)
def load_dividend_forecast():
    return get_dividend_forecast()

df_yearly, df_current_year, df_all_time = load_dividend_data()

# --- HISTORICAL SECTION ---
col1, col2 = st.columns([2, 1])

with col1:
    styled_subheader("Dividends by Year")
    if not df_yearly.empty:
        fig = px.bar(
            df_yearly, x='year', y='total',
            color_discrete_sequence=[COLORS["green"]],
        )
        fig.update_layout(**get_plotly_layout(
            showlegend=False,
            xaxis=dict(title="", gridcolor="#21262D", linecolor="#30363D",
                       zerolinecolor="#30363D", title_font=dict(color="#8B949E"),
                       tickfont=dict(color="#8B949E")),
            yaxis=dict(title=f"Amount ({BASE_CURRENCY})", gridcolor="#21262D",
                       linecolor="#30363D", zerolinecolor="#30363D",
                       title_font=dict(color="#8B949E"), tickfont=dict(color="#8B949E")),
        ))
        fig.update_traces(marker_line_color="#0E1117", marker_line_width=1)
        st.plotly_chart(fig, use_container_width=True)

with col2:
    styled_subheader("Top Payers (Current Year)")
    st.dataframe(
        df_current_year,
        column_config={
            "symbol": st.column_config.TextColumn("Instrument"),
            "total": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
        },
        use_container_width=True,
        hide_index=True
    )

st.divider()

styled_subheader("Top Payers (All Time)")
st.dataframe(
    df_all_time.head(30),
    column_config={
        "symbol": st.column_config.TextColumn("Instrument"),
        "total": st.column_config.NumberColumn(f"Total Payout ({BASE_CURRENCY})", format="localized"),
    },
    use_container_width=True,
    hide_index=True
)

st.divider()

# --- FORECAST SECTION ---
styled_subheader("Dividend Forecast")

with st.spinner("Fetching dividend forecast..."):
    df_forecast, forecast_summary = load_dividend_forecast()

if not df_forecast.empty:
    st.metric(
        label="Estimated Annual Dividends",
        value=f"{forecast_summary['total_estimate_local']:,.0f} {BASE_CURRENCY}"
    )

    # Sort by NOK value and display
    df_display = df_forecast.sort_values('annual_estimate_local', ascending=False)
    st.dataframe(
        df_display,
        column_config={
            "symbol": st.column_config.TextColumn("Symbol"),
            "quantity": st.column_config.NumberColumn("Shares", format="%d"),
            "dividend_per_share": st.column_config.NumberColumn("Div/Share", format="%.2f"),
            "currency": st.column_config.TextColumn("Currency"),
            "annual_estimate": st.column_config.NumberColumn("Annual Est.", format="%d"),
            "annual_estimate_local": st.column_config.NumberColumn(f"Est. ({BASE_CURRENCY})", format="%d"),
            "source": st.column_config.TextColumn("Source"),
        },
        use_container_width=True,
        hide_index=True
    )
    st.caption(
        f"**yahoo** = Forward dividend rate | **ttm** = Trailing 12-month history | "
        f"Coverage: {forecast_summary['yahoo_count']} yahoo, {forecast_summary['ttm_count']} ttm, "
        f"{forecast_summary['no_data_count']} no data"
    )
else:
    st.info("No dividend-paying holdings found.")
