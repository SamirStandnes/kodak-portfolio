import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.shared.calculations import get_fee_details, get_fee_analysis, get_platform_fees
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, styled_subheader, get_plotly_layout, COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Fee Analysis", page_icon="💸", layout="wide")
apply_theme()

page_header("Fee Analysis", "Trading costs and platform fees")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_fee_data():
    return get_fee_details()

df_yearly, df_currency, df_top = load_fee_data()

total_fees = df_yearly['total'].sum()
st.metric("Total Fees Paid (All Time)", format_local(total_fees))

col1, col2 = st.columns(2)

with col1:
    styled_subheader("Fees by Year")
    if not df_yearly.empty:
        fig = px.bar(
            df_yearly, x='year', y='total',
            color_discrete_sequence=[COLORS["yellow"]],
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
    styled_subheader("Fees by Currency")
    st.dataframe(
        df_currency,
        column_config={
            "currency": st.column_config.TextColumn("Currency"),
            "total": st.column_config.NumberColumn(f"Total Fees ({BASE_CURRENCY})", format="localized"),
        },
        use_container_width=True,
        hide_index=True
    )

st.divider()
styled_subheader("Recent Individual Fees")
st.dataframe(
    df_top,
    column_config={
        "date": st.column_config.DateColumn("Date"),
        "currency": st.column_config.TextColumn("Fee Currency"),
        "amount_local": st.column_config.NumberColumn(f"Fee ({BASE_CURRENCY})", format="localized"),
        "source_file": st.column_config.TextColumn("Source"),
    },
    use_container_width=True,
    hide_index=True
)

st.divider()
styled_subheader("Fee Efficiency by Broker")
st.caption(f"Cost per 100 {BASE_CURRENCY} traded (lower is better)")

df_broker = get_fee_analysis()
if not df_broker.empty:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.dataframe(
            df_broker,
            column_config={
                "broker": st.column_config.TextColumn("Broker"),
                "total_traded": st.column_config.NumberColumn(f"Total Traded ({BASE_CURRENCY})", format="localized"),
                "total_fees": st.column_config.NumberColumn(f"Total Fees ({BASE_CURRENCY})", format="localized"),
                "fee_per_100": st.column_config.NumberColumn(f"Fee per 100 {BASE_CURRENCY}", format="%.4f"),
                "num_trades": st.column_config.NumberColumn("# Trades"),
            },
            use_container_width=True,
            hide_index=True
        )

    with col2:
        fig = px.bar(
            df_broker, x='broker', y='fee_per_100',
            color_discrete_sequence=[COLORS["red"]],
        )
        fig.update_layout(**get_plotly_layout(
            showlegend=False,
            xaxis=dict(title="", gridcolor="#21262D", linecolor="#30363D",
                       zerolinecolor="#30363D", title_font=dict(color="#8B949E"),
                       tickfont=dict(color="#8B949E")),
            yaxis=dict(title=f"Fee per 100 {BASE_CURRENCY}", gridcolor="#21262D",
                       linecolor="#30363D", zerolinecolor="#30363D",
                       title_font=dict(color="#8B949E"), tickfont=dict(color="#8B949E")),
        ))
        fig.update_traces(marker_line_color="#0E1117", marker_line_width=1)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trading data available for fee analysis.")

st.divider()
styled_subheader("Platform & Custody Fees by Broker")
st.caption("Monthly subscription/custody fees (not per-trade)")

df_platform = get_platform_fees()
if not df_platform.empty:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.dataframe(
            df_platform,
            column_config={
                "broker": st.column_config.TextColumn("Broker"),
                "total_fees": st.column_config.NumberColumn(f"Total Fees ({BASE_CURRENCY})", format="localized"),
                "monthly_avg": st.column_config.NumberColumn(f"Avg Monthly ({BASE_CURRENCY})", format="%.2f"),
                "num_charges": st.column_config.NumberColumn("# Charges"),
            },
            use_container_width=True,
            hide_index=True
        )

    with col2:
        fig = px.bar(
            df_platform, x='broker', y='monthly_avg',
            color_discrete_sequence=[COLORS["purple"]],
        )
        fig.update_layout(**get_plotly_layout(
            showlegend=False,
            xaxis=dict(title="", gridcolor="#21262D", linecolor="#30363D",
                       zerolinecolor="#30363D", title_font=dict(color="#8B949E"),
                       tickfont=dict(color="#8B949E")),
            yaxis=dict(title=f"Avg Monthly ({BASE_CURRENCY})", gridcolor="#21262D",
                       linecolor="#30363D", zerolinecolor="#30363D",
                       title_font=dict(color="#8B949E"), tickfont=dict(color="#8B949E")),
        ))
        fig.update_traces(marker_line_color="#0E1117", marker_line_width=1)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No platform fee data available.")
