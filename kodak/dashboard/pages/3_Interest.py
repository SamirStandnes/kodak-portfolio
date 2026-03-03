import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.shared.calculations import get_interest_details
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, styled_subheader, get_plotly_layout, COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Interest Analysis", page_icon="🏦", layout="wide")
apply_theme()

page_header("Interest Analysis", "Interest charges across accounts")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_interest_data():
    return get_interest_details()

df_yearly, df_currency, df_top = load_interest_data()

# Summary
total_interest = df_yearly['total'].sum()
st.metric("Total Interest Paid (All Time)", format_local(total_interest))

# Charts
col1, col2 = st.columns(2)

with col1:
    styled_subheader("Interest by Year")
    if not df_yearly.empty:
        fig = px.bar(
            df_yearly, x='year', y='total',
            color_discrete_sequence=[COLORS["blue"]],
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
    styled_subheader("Interest by Currency")
    st.dataframe(
        df_currency,
        column_config={
            "currency": st.column_config.TextColumn("Currency"),
            "total": st.column_config.NumberColumn(f"Total Interest ({BASE_CURRENCY})", format="localized"),
        },
        use_container_width=True,
        hide_index=True
    )

# Table
styled_subheader("Recent Interest Payments")
st.dataframe(
    df_top,
    column_config={
        "date": st.column_config.DateColumn("Date"),
        "currency": st.column_config.TextColumn("Curr"),
        "amount": st.column_config.NumberColumn("Amount (Orig)", format="localized"),
        "amount_local": st.column_config.NumberColumn(f"Amount ({BASE_CURRENCY})", format="localized"),
        "source_file": st.column_config.TextColumn("Source"),
    },
    use_container_width=True,
    hide_index=True
)
