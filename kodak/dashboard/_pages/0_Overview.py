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
    render_chart, display_aggrid, load_valued_holdings, load_portfolio_history,
    price_freshness,
)
from kodak.shared.calculations import get_income_and_costs, get_total_cash_local

page_setup("Portfolio Overview", "📈", "Net worth, value over time, allocation and what moved since the last price refresh.")


@st.cache_data(ttl=CACHE_TTL)
def load_cash_and_income():
    return get_total_cash_local(), get_income_and_costs()


df_val = load_valued_holdings()
cash, income = load_cash_and_income()
history = load_portfolio_history()
latest_date, prev_date = price_freshness(df_val)

market_value = float(df_val['market_value_local'].sum())
cost_basis = float(df_val['cost_basis_local'].sum())
net_worth = market_value + cash
total_gain = market_value - cost_basis
total_return_pct = (market_value / cost_basis - 1) * 100 if cost_basis > 0 else 0
change_value = float(df_val['day_change_local'].sum())
change_pct = (change_value / (market_value - change_value) * 100) if (market_value - change_value) > 0 else 0

# --- KEY METRICS ---
col1, col2, col3 = st.columns(3)
col1.metric(
    "Total Net Equity", format_local(net_worth),
    delta=f"{format_local(change_value)} ({format_pct(change_pct, 2, sign=True)})" if prev_date else None,
    help=f"Holdings + cash. Change is since the previous price refresh ({prev_date})." if prev_date else None,
)
col2.metric("Stock Holdings", format_local(market_value))
col3.metric("Cash & Margin", format_local(cash),
            help="Running balance per settlement currency at today's FX rate. Negative = margin usage")

col4, col5, col6 = st.columns(3)
col4.metric("Unrealized P&L", format_local(total_gain), format_pct(total_return_pct, 1, sign=True))
col5.metric("Cost Basis", format_local(cost_basis))
col6.metric("Dividends (All Time)", format_local(income['dividends']))

if latest_date:
    unpriced = int((~df_val['has_price']).sum())
    note = f"Prices as of **{latest_date}**"
    if prev_date:
        note += f" · change measured against **{prev_date}**"
    if unpriced:
        note += f" · {unpriced} position(s) without a price are carried at cost"
    st.caption(note)

st.divider()

# --- VALUE OVER TIME ---
st.subheader("Portfolio Value")
if history.empty or len(history) < 2:
    st.info("Not enough price history yet. The curve appears once prices have been stored for two or more dates.")
else:
    first, last = history.iloc[0], history.iloc[-1]
    ytd_start = history[history['date'] < pd.Timestamp(year=last['date'].year, month=1, day=1)]
    base = ytd_start.iloc[-1] if not ytd_start.empty else first
    pnl_period = (last['total_value'] - base['total_value']) - (last['net_deposits'] - base['net_deposits'])
    pnl_pct = pnl_period / base['total_value'] * 100 if base['total_value'] > 0 else 0
    label = "Year to Date P&L" if not ytd_start.empty else f"P&L since {first['date']:%d %b %Y}"

    m1, m2, m3 = st.columns(3)
    m1.metric(label, format_local(pnl_period), format_pct(pnl_pct, 1, sign=True),
              help="Change in total value minus net deposits over the period.")
    m2.metric("Net Deposits (All Time)", format_local(last['net_deposits']),
              help="Deposits minus withdrawals across all accounts.")
    m3.metric("Total Gain vs Deposits", format_local(last['total_value'] - last['net_deposits']),
              help="Current value minus everything you have put in.")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history['date'], y=history['total_value'], name='Total Value',
        mode='lines', line=dict(color=COLORS['primary'], width=2.5),
        fill='tozeroy', fillcolor='rgba(102,126,234,0.12)',
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>Total Value</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=history['date'], y=history['net_deposits'], name='Net Deposits',
        mode='lines', line=dict(color=COLORS['neutral'], width=1.5, dash='dot'),
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>Net Deposits</extra>",
    ))
    fig.update_layout(
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1Y", step="year", stepmode="backward"),
                    dict(count=3, label="3Y", step="year", stepmode="backward"),
                    dict(label="All", step="all"),
                ],
                bgcolor=COLORS['bg_surface'], activecolor=COLORS['primary'],
                font=dict(color=COLORS['text']),
            ),
        ),
        yaxis=dict(title=BASE_CURRENCY, rangemode='tozero'),
        legend=dict(orientation='h', y=1.08, x=0),
        margin=dict(l=40, r=20, t=50, b=40),
    )
    render_chart(fig)
    st.caption(
        f"Built from closing prices and FX rates stored in the database "
        f"({first['date']:%d %b %Y} → {last['date']:%d %b %Y}); prices are carried forward "
        "between stored dates. Holdings without a price are carried at net cash invested. "
        "Extend or repair the history with `python -m kodak.maintenance.backfill_prices`."
    )

st.divider()

# --- MOVERS SINCE LAST REFRESH ---
movers = df_val[df_val['day_change_pct'].notna()]
if not movers.empty and prev_date:
    st.subheader(f"Movers since {prev_date}")
    mcol1, mcol2 = st.columns(2)
    mover_cols = {
        "Symbol":   {"width": 120},
        "Change %": {"type": "percent", "decimals": 2, "color_signed": True, "width": 120},
        f"Change ({BASE_CURRENCY})": {"label": f"Change ({BASE_CURRENCY})", "type": "currency", "decimals": 0, "color_signed": True, "width": 150},
    }

    def mover_frame(frame):
        return pd.DataFrame({
            "Symbol": frame['symbol'],
            "Change %": frame['day_change_pct'].round(2),
            f"Change ({BASE_CURRENCY})": frame['day_change_local'].round(),
        })

    with mcol1:
        st.caption("Top gainers")
        display_aggrid(mover_frame(movers.nlargest(5, 'day_change_pct')), columns=mover_cols, height=230)
    with mcol2:
        st.caption("Top losers")
        display_aggrid(mover_frame(movers.nsmallest(5, 'day_change_pct')), columns=mover_cols, height=230)
    st.divider()

# --- ALLOCATION ---
st.subheader("Portfolio Allocation")

if not df_val.empty and market_value > 0:
    palette = [COLORS['primary'], COLORS['positive'], COLORS['warning'],
               COLORS['purple'], COLORS['light_blue'], COLORS['negative'], COLORS['neutral']]
    df_alloc = df_val.rename(columns={
        'market_value_local': 'Market Value', 'sector': 'Sector', 'region': 'Region',
        'country': 'Country', 'asset_class': 'Asset Class', 'currency': 'Currency',
    })

    def make_pie(col, title):
        fig = px.pie(df_alloc, values='Market Value', names=col, title=title,
                     color_discrete_sequence=palette, hole=0.4)
        fig.update_traces(
            textposition='inside', texttemplate='%{label}<br>%{percent:.1%}',
            marker=dict(line=dict(color=COLORS['bg'], width=2)),
            hovertemplate=f"<b>%{{label}}</b><br>%{{value:,.0f}} {BASE_CURRENCY}<br>%{{percent:.1%}}<extra></extra>",
        )
        fig.update_layout(hovermode='closest', uniformtext_minsize=11, uniformtext_mode='hide',
                          margin=dict(l=10, r=10, t=48, b=10))
        return fig

    tabs = st.tabs(["Sector", "Region", "Currency", "Asset Class", "Country"])
    for tab, (col, title) in zip(tabs, [
        ('Sector', 'By Sector'), ('Region', 'By Region'), ('Currency', 'By Currency'),
        ('Asset Class', 'By Asset Class'), ('Country', 'By Country'),
    ]):
        with tab:
            render_chart(make_pie(col, title))
else:
    st.info("No allocation data available.")
