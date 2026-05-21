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

# --- KEY METRICS ---
total_interest = df_yearly['total'].sum() if not df_yearly.empty else 0
num_currencies = len(df_currency) if not df_currency.empty else 0

col1, col2 = st.columns(2)
col1.metric("Total Interest Paid (All Time)", format_local(total_interest))
col2.metric("Currencies", num_currencies)

st.divider()

# --- TABS ---
tab1, tab2 = st.tabs(["Yearly Overview", "Recent Payments"])

with tab1:
    tcol1, tcol2 = st.columns([2, 1])
    with tcol1:
        if not df_yearly.empty:
            fig = px.bar(
                df_yearly, x='year', y='total',
                labels={'total': BASE_CURRENCY, 'year': ''},
                color_discrete_sequence=[COLORS['primary']],
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
            st.plotly_chart(fig, use_container_width=True, theme=None)
    with tcol2:
        st.caption("By Currency")
        display_table(df_currency, {
            "currency": text_col("Currency"),
            "total": number_col(f"Total ({BASE_CURRENCY})"),
        }, height=250)

with tab2:
    display_table(df_top, {
        "date": date_col(),
        "currency": text_col("Curr"),
        "amount": number_col("Amount (Orig)"),
        "amount_local": number_col(f"Amount ({BASE_CURRENCY})"),
        "source_file": text_col("Source"),
    }, height=400)
