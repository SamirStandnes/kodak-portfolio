import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local,
    display_table, number_col, text_col, apply_plotly_theme,
)
from kodak.shared.calculations import get_yearly_equity_curve, get_yearly_contribution, get_total_xirr

page_setup("Performance", "📈")


@st.cache_data(ttl=CACHE_TTL)
def load_total_xirr():
    return get_total_xirr()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_equity_curve():
    return get_yearly_equity_curve()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_contribution(year: str):
    return get_yearly_contribution(year)


# --- 1. All-Time ---
with st.spinner("Calculating All-Time Performance..."):
    total_xirr = load_total_xirr()

st.metric("All-Time XIRR (Annualized)", f"{format_local(total_xirr, 2)}%")
st.divider()

# --- 2. Yearly Timeline ---
with st.spinner("Fetching Yearly Data..."):
    df_years, missing_prices = load_yearly_equity_curve()

if not df_years.empty:
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df_years['year'], y=df_years['end_equity'],
        name='End Equity', marker_color=COLORS['primary'], yaxis='y',
    ))

    fig.add_trace(go.Scatter(
        x=df_years['year'], y=df_years['return_pct'],
        name='Annual Return (%)', mode='lines+markers',
        line=dict(color=COLORS['positive'], width=3), yaxis='y2',
    ))

    fig.update_layout(
        title='Yearly Equity & Returns',
        xaxis=dict(title=''),
        yaxis=dict(title=f'Equity ({BASE_CURRENCY})', side='left', showgrid=False),
        yaxis2=dict(title='Return (%)', side='right', overlaying='y', showgrid=True),
        legend=dict(x=0.01, y=0.99),
    )
    apply_plotly_theme(fig)
    st.plotly_chart(fig, use_container_width=True)

    # --- Cumulative Equity Curve ---
    st.subheader("Cumulative Equity Curve")
    fig_curve = go.Figure()
    fig_curve.add_trace(go.Scatter(
        x=df_years['year'], y=df_years['end_equity'],
        mode='lines+markers+text',
        fill='tozeroy',
        fillcolor='rgba(74, 144, 217, 0.15)',
        line=dict(color=COLORS['primary'], width=3),
        text=[format_local(v) for v in df_years['end_equity']],
        textposition='top center',
        textfont=dict(size=10),
    ))
    fig_curve.update_layout(
        xaxis_title='', yaxis_title=f'Portfolio Value ({BASE_CURRENCY})',
    )
    apply_plotly_theme(fig_curve)
    st.plotly_chart(fig_curve, use_container_width=True)

    # --- Drawdown Chart ---
    st.subheader("Drawdown from Peak")
    peak = df_years['end_equity'].cummax()
    drawdown_pct = ((df_years['end_equity'] - peak) / peak * 100).fillna(0)

    fig_dd = go.Figure()
    fig_dd.add_trace(go.Bar(
        x=df_years['year'], y=drawdown_pct,
        marker_color=COLORS['negative'],
    ))
    fig_dd.update_layout(
        yaxis_title='Drawdown (%)',
        xaxis_title='',
    )
    apply_plotly_theme(fig_dd)
    st.plotly_chart(fig_dd, use_container_width=True)

    # --- Monthly Returns Heatmap ---
    st.subheader("Monthly Returns Heatmap")
    st.caption("Based on yearly XIRR spread evenly across months (monthly data requires daily pricing)")

    # Build a monthly grid from yearly returns
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    years_list = df_years['year'].tolist()
    heatmap_data = []
    for _, row in df_years.iterrows():
        annual_return = row['return_pct']
        # Convert annual to approx monthly
        monthly_return = ((1 + annual_return / 100) ** (1 / 12) - 1) * 100
        for m in months:
            heatmap_data.append({
                'Year': row['year'], 'Month': m, 'Return %': round(monthly_return, 2)
            })

    df_heatmap = pd.DataFrame(heatmap_data)
    pivot = df_heatmap.pivot(index='Year', columns='Month', values='Return %')
    pivot = pivot[months]  # ensure month order

    fig_heat = px.imshow(
        pivot.values,
        x=months,
        y=pivot.index.tolist(),
        color_continuous_scale='RdBu',
        color_continuous_midpoint=0,
        aspect='auto',
        text_auto='.1f',
    )
    fig_heat.update_layout(
        xaxis_title='', yaxis_title='',
        yaxis=dict(autorange='reversed'),
    )
    apply_plotly_theme(fig_heat)
    st.plotly_chart(fig_heat, use_container_width=True)

    st.divider()

    st.subheader("Yearly Summary")
    display_table(df_years, {
        "year": text_col("Year"),
        "start_equity": number_col("Start Value"),
        "net_flow": number_col("Net Deposits"),
        "end_equity": number_col("End Value"),
        "profit": number_col(f"Profit ({BASE_CURRENCY})"),
        "return_pct": number_col("XIRR %", fmt="%.2f%%"),
    }, height=350)

    if missing_prices:
        with st.expander("Missing / Fallback Prices Used"):
            st.dataframe(pd.DataFrame(missing_prices))
else:
    st.info("No yearly data available.")

st.divider()

# --- 3. Detailed Year View ---
st.subheader("Detailed Analysis by Year")
selected_year = st.selectbox(
    "Select Year",
    df_years['year'].sort_values(ascending=False) if not df_years.empty else [],
)

if selected_year:
    with st.spinner(f"Analyzing {selected_year}..."):
        df_contrib, year_xirr, missing_prices_year = load_yearly_contribution(selected_year)

    st.metric(f"{selected_year} XIRR", f"{year_xirr:.2f}%")

    if not df_contrib.empty:
        df_tree = df_contrib[abs(df_contrib['Contribution %']) > 0.05].copy()

        fig_tree = px.treemap(
            df_tree, path=['Symbol'],
            values=abs(df_tree['Contribution %']),
            color='Contribution %',
            color_continuous_scale='RdBu',
            color_continuous_midpoint=0,
            title=f"Performance Contribution ({selected_year})",
        )
        apply_plotly_theme(fig_tree)
        st.plotly_chart(fig_tree, use_container_width=True)

        display_table(df_contrib, {
            "Symbol": text_col("Instrument"),
            "SOY Value": number_col("SOY Value"),
            "Net Additions": number_col("Net Additions"),
            "EOY Value": number_col("EOY Value"),
            "Dividends": number_col("Divs"),
            "Profit": number_col("Profit"),
            "IRR %": number_col("IRR %", fmt="%.1f%%"),
            "Contribution %": number_col("Contr. %", fmt="%.2f%%"),
        })

        st.caption("""
        **Legend:** [Items in Brackets] = non-instrument totals (Fees, Interest, Tax).
        [Cash FX & Float] = P&L from uninvested cash or margin debt due to currency movements.
        """)

        if missing_prices_year:
            with st.expander(f"Missing / Fallback Prices for {selected_year}"):
                st.info("Detailed analysis requires pricing for both Start of Year and End of Year. The Timeline view only checks End of Year.")
                st.dataframe(pd.DataFrame(missing_prices_year))
