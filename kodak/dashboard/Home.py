import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup,
    format_local, apply_plotly_theme, convert_to_base,
)
from kodak.shared.db import get_connection, execute_query
from kodak.shared.calculations import get_holdings, get_income_and_costs

page_setup("Portfolio Overview", "📈")

# --- DATA ---
@st.cache_data(ttl=CACHE_TTL)
def load_summary_data():
    conn = get_connection()

    df_holdings = get_holdings()

    instruments = pd.read_sql_query(
        'SELECT id, sector, region, country, asset_class FROM instruments', conn
    )
    prices = pd.read_sql_query('''
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
            total_market_value += val
            total_cost += row['cost_basis_local']

            allocation_data.append({
                'Market Value': val,
                'Sector': meta.get('sector') or 'Unknown',
                'Region': meta.get('region') or 'Unknown',
                'Asset Class': meta.get('asset_class') or 'Equity',
            })

    total_cash_base = pd.read_sql_query(
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

# --- KEY METRICS ---
col1, col2, col3 = st.columns(3)
col1.metric("Total Net Equity", format_local(net_worth))
col2.metric("Stock Holdings", format_local(data['market_value']))
col3.metric("Cash & Margin", format_local(data['cash']), help="Negative = margin usage")

col4, col5, col6 = st.columns(3)
col4.metric("Unrealized P&L", format_local(total_gain), f"{format_local(total_return_pct, 1)}%")
col5.metric("Cost Basis", format_local(data['cost_basis']))
col6.metric("Dividends (All Time)", format_local(data['dividends']))

st.divider()

# --- ALLOCATION ---
st.subheader("Portfolio Allocation")
df_alloc = data['allocation']

if not df_alloc.empty:
    acol1, acol2 = st.columns(2)

    palette = [COLORS['primary'], COLORS['positive'], COLORS['warning'],
               COLORS['purple'], COLORS['light_blue'], COLORS['negative'], COLORS['neutral']]

    with acol1:
        fig_sector = px.pie(df_alloc, values='Market Value', names='Sector', title='By Sector',
                            color_discrete_sequence=palette, hole=0.4)
        apply_plotly_theme(fig_sector)
        st.plotly_chart(fig_sector, use_container_width=True)

    with acol2:
        fig_region = px.pie(df_alloc, values='Market Value', names='Region', title='By Region',
                            color_discrete_sequence=palette, hole=0.4)
        apply_plotly_theme(fig_region)
        st.plotly_chart(fig_region, use_container_width=True)
else:
    st.info("No allocation data available.")
