import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local, format_pct,
    display_table, number_col, text_col, render_chart,
)
from kodak.shared.calculations import (
    get_yearly_equity_curve, get_yearly_contribution, get_total_xirr, get_realized_performance,
)

page_setup("Performance", "📊")


@st.cache_data(ttl=CACHE_TTL)
def load_total_xirr():
    return get_total_xirr()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_equity_curve():
    return get_yearly_equity_curve()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_contribution(year: str):
    return get_yearly_contribution(year)


@st.cache_data(ttl=CACHE_TTL)
def load_realized_performance():
    return get_realized_performance()


# --- 1. All-Time ---
with st.spinner("Calculating All-Time Performance..."):
    total_xirr = load_total_xirr()

with st.spinner("Fetching Yearly Data..."):
    df_years, missing_prices = load_yearly_equity_curve()

df_realized = load_realized_performance()

k1, k2, k3 = st.columns(3)
k1.metric("All-Time XIRR (Annualized)", format_pct(total_xirr, 2),
          help="Money-weighted return on all deposits and withdrawals, valued at live prices.")
if not df_years.empty:
    total_profit = df_years['profit'].sum()
    k2.metric("Cumulative Profit", format_local(total_profit),
              help="Sum of yearly profit (end value − start value − net deposits).")
    best = df_years.loc[df_years['return_pct'].idxmax()]
    k3.metric("Best Year", f"{best['year']}: {format_pct(best['return_pct'], 1, sign=True)}")
st.divider()

# --- 2. Yearly Timeline ---
if not df_years.empty:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_years['year'], y=df_years['end_equity'],
        name='End Equity', marker_color=COLORS['primary'], yaxis='y',
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>End Equity</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_years['year'], y=df_years['return_pct'],
        name='Annual Return (XIRR)', mode='lines+markers',
        line=dict(color=COLORS['positive'], width=3), yaxis='y2',
        hovertemplate="%{y:+.2f}%<extra>XIRR</extra>",
    ))
    fig.update_layout(
        title='Yearly Equity & Returns',
        yaxis=dict(side='left', showgrid=False, title=f'Equity ({BASE_CURRENCY})'),
        yaxis2=dict(side='right', overlaying='y', showgrid=True, title='Return (%)',
                    zeroline=True, zerolinecolor=COLORS['border']),
        legend=dict(x=0.01, y=0.99),
        xaxis_title='', xaxis=dict(type='category'),
    )
    render_chart(fig)

    st.subheader("Yearly Summary")
    display_table(df_years, {
        "year": text_col("Year"),
        "start_equity": number_col("Start Value"),
        "net_flow": number_col("Net Deposits"),
        "end_equity": number_col("End Value"),
        "profit": number_col(f"Profit ({BASE_CURRENCY})"),
        "return_pct": number_col("XIRR %", fmt="%.2f%%"),
    }, height=min(400, 40 * len(df_years) + 60))

    if missing_prices:
        with st.expander("Missing / Fallback Prices Used"):
            st.dataframe(pd.DataFrame(missing_prices), width="stretch", hide_index=True)
else:
    st.info("No yearly data available.")

st.divider()

# --- 3. Realized P&L by Year ---
st.subheader("Realized P&L by Year")
st.caption("What actually hit the account each year: gains on sales, dividends, interest, fees and withholding tax. "
           "Unrealized gains on open positions are not included.")
if df_realized.empty:
    st.info("No realized data available.")
else:
    components = [
        ('realized_gl', 'Realized Gains', COLORS['primary']),
        ('dividends', 'Dividends', COLORS['positive']),
        ('interest', 'Interest', COLORS['warning']),
        ('fees', 'Fees', COLORS['negative']),
        ('tax', 'Tax', COLORS['purple']),
    ]
    fig_r = go.Figure()
    for col, label, color in components:
        fig_r.add_trace(go.Bar(
            x=df_realized['year'], y=df_realized[col], name=label, marker_color=color,
            hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>{label}</extra>",
        ))
    fig_r.add_trace(go.Scatter(
        x=df_realized['year'], y=df_realized['total_pl'], name='Net', mode='lines+markers',
        line=dict(color=COLORS['text'], width=2), marker=dict(size=8),
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>Net</extra>",
    ))
    fig_r.update_layout(
        barmode='relative', xaxis=dict(type='category', title=''),
        yaxis_title=BASE_CURRENCY, legend=dict(orientation='h', y=1.08, x=0),
    )
    render_chart(fig_r)

    display_table(df_realized[['year', 'realized_gl', 'dividends', 'interest', 'fees', 'tax', 'total_pl']], {
        "year": text_col("Year"),
        "realized_gl": number_col("Realized Gains"),
        "dividends": number_col("Dividends"),
        "interest": number_col("Interest"),
        "fees": number_col("Fees"),
        "tax": number_col("Tax"),
        "total_pl": number_col(f"Net ({BASE_CURRENCY})"),
    }, height=min(400, 40 * len(df_realized) + 60))

st.divider()

# --- 4. Detailed Year View ---
st.subheader("Detailed Analysis by Year")
selected_year = st.selectbox(
    "Select Year",
    df_years['year'].sort_values(ascending=False).tolist() if not df_years.empty else [],
)

if selected_year:
    with st.spinner(f"Analyzing {selected_year}..."):
        df_contrib, year_xirr, missing_prices_year = load_yearly_contribution(selected_year)

    st.metric(f"{selected_year} XIRR", format_pct(year_xirr, 2))

    if not df_contrib.empty:
        df_tree = df_contrib[abs(df_contrib['Contribution %']) > 0.05].copy()

        if not df_tree.empty:
            fig_tree = px.treemap(
                df_tree, path=['Symbol'],
                values=abs(df_tree['Contribution %']),
                color='Contribution %',
                color_continuous_scale=[COLORS['negative'], COLORS['bg_surface'], COLORS['positive']],
                color_continuous_midpoint=0,
                title=f"Performance Contribution ({selected_year})",
            )
            fig_tree.update_traces(
                hovertemplate="<b>%{label}</b><br>Contribution: %{color:+.2f} pp<extra></extra>")
            fig_tree.update_layout(hovermode='closest')
            render_chart(fig_tree)

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
                st.dataframe(pd.DataFrame(missing_prices_year), width="stretch", hide_index=True)
