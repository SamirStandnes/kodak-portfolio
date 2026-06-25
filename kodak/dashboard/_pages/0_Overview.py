import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup,
    format_local, apply_plotly_theme, convert_to_base,
)
from kodak.shared.db import get_connection, query_df
from kodak.shared.calculations import get_holdings, get_income_and_costs

page_setup("Portfolio Overview", "📈")


@st.cache_data(ttl=CACHE_TTL)
def load_summary_data():
    conn = get_connection()

    df_holdings = get_holdings()

    instruments = query_df(
        'SELECT id, sector, region, country, asset_class, currency FROM instruments', conn
    )
    prices = query_df('''
        SELECT mp.instrument_id, mp.close, i.currency
        FROM market_prices mp
        JOIN instruments i ON mp.instrument_id = i.id
        WHERE (mp.instrument_id, mp.date) IN (
            SELECT instrument_id, MAX(date) FROM market_prices GROUP BY instrument_id
        )
    ''', conn)

    price_map = {r['instrument_id']: {'price': r['close'], 'currency': r['currency']} for _, r in prices.iterrows()}
    meta_map = instruments.set_index('id').to_dict('index')

    total_market_value = 0
    total_cost = 0
    fx_cache = {}
    allocation_data = []

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        mkt = price_map.get(inst_id)
        meta = meta_map.get(inst_id, {})

        if mkt:
            price = mkt['price']
            curr = mkt['currency']
            val = row['quantity'] * convert_to_base(price, curr, fx_cache)
        else:
            # No current market price (illiquid/private holding, or prices not
            # yet populated in this DB) — carry the position at cost basis so it
            # still appears in allocation instead of being silently dropped.
            # Without this, a momentarily empty market_prices table makes EVERY
            # holding vanish and the page shows "No allocation data available"
            # even though the portfolio plainly exists.
            val = row['cost_basis_local']

        total_market_value += val
        total_cost += row['cost_basis_local']

        allocation_data.append({
            'Market Value': val,
            'Sector': meta.get('sector') or 'Unknown',
            'Region': meta.get('region') or 'Unknown',
            'Country': meta.get('country') or 'Unknown',
            'Asset Class': meta.get('asset_class') or 'Equity',
            'Currency': meta.get('currency') or 'Unknown',
        })

    total_cash_base = query_df(
        "SELECT COALESCE(SUM(amount_local), 0) as total FROM transactions", conn
    ).iloc[0]['total']

    income = get_income_and_costs()
    conn.close()

    return {
        "market_value": total_market_value,
        "cost_basis": total_cost,
        "cash": total_cash_base,
        "dividends": income['dividends'],
        "interest": income['interest'],
        "fees": income['fees'],
        "allocation": pd.DataFrame(allocation_data),
    }


data = load_summary_data()

net_worth = data['market_value'] + data['cash']
total_gain = data['market_value'] - data['cost_basis']
total_return_pct = (data['market_value'] / data['cost_basis'] - 1) * 100 if data['cost_basis'] > 0 else 0

col1, col2, col3 = st.columns(3)
col1.metric("Total Net Equity", format_local(net_worth))
col2.metric("Stock Holdings", format_local(data['market_value']))
col3.metric("Cash & Margin", format_local(data['cash']), help="Negative = margin usage")

col4, col5, col6 = st.columns(3)
col4.metric("Unrealized P&L", format_local(total_gain), f"{format_local(total_return_pct, 1)}%")
col5.metric("Cost Basis", format_local(data['cost_basis']))
col6.metric("Dividends (All Time)", format_local(data['dividends']))

st.divider()

st.subheader("Portfolio Allocation")
df_alloc = data['allocation']

if not df_alloc.empty:
    palette = [COLORS['primary'], COLORS['positive'], COLORS['warning'],
               COLORS['purple'], COLORS['light_blue'], COLORS['negative'], COLORS['neutral']]

    def make_pie(df, col, title):
        fig = px.pie(df, values='Market Value', names=col, title=title,
                     color_discrete_sequence=palette, hole=0.4)
        apply_plotly_theme(fig)
        return fig

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Sector", "Region", "Currency", "Asset Class", "Country"])

    with tab1:
        st.plotly_chart(make_pie(df_alloc, 'Sector', 'By Sector'), use_container_width=True, theme=None)
    with tab2:
        st.plotly_chart(make_pie(df_alloc, 'Region', 'By Region'), use_container_width=True, theme=None)
    with tab3:
        st.plotly_chart(make_pie(df_alloc, 'Currency', 'By Currency'), use_container_width=True, theme=None)
    with tab4:
        st.plotly_chart(make_pie(df_alloc, 'Asset Class', 'By Asset Class'), use_container_width=True, theme=None)
    with tab5:
        st.plotly_chart(make_pie(df_alloc, 'Country', 'By Country'), use_container_width=True, theme=None)
else:
    st.info("No allocation data available.")
