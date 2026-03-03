import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.shared.db import get_connection, execute_query
from kodak.shared.calculations import get_holdings, get_income_and_costs
from kodak.shared.market_data import get_exchange_rate
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, styled_subheader, get_plotly_layout, CHART_COLORS, COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(
    page_title=f"Kodak Portfolio ({BASE_CURRENCY})",
    page_icon="📈",
    layout="wide"
)
apply_theme()

page_header("Portfolio Overview", "Your investments at a glance")

# --- DATA FETCHING ---
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_summary_data():
    conn = get_connection()

    # 1. Holdings & Market Value (now including metadata)
    df_holdings = get_holdings()

    # Get latest prices and metadata
    instruments = pd.read_sql_query('''
        SELECT id, sector, region, country, asset_class
        FROM instruments
    ''', conn)

    prices = pd.read_sql_query('''
        SELECT mp.instrument_id, mp.close, i.currency
        FROM market_prices mp
        JOIN instruments i ON mp.instrument_id = i.id
        WHERE (mp.instrument_id, mp.date) IN (
            SELECT instrument_id, MAX(date)
            FROM market_prices
            GROUP BY instrument_id
        )
    ''', conn)

    price_map = {row['instrument_id']: {'price': row['close'], 'currency': row['currency']} for _, row in prices.iterrows()}
    meta_map = instruments.set_index('id').to_dict('index')

    # Calculate Market Value & Prepare Allocation Data
    total_market_value = 0
    total_cost = 0
    fx_cache = {}
    allocation_data = []

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        mkt = price_map.get(inst_id)
        meta = meta_map.get(inst_id, {})

        if mkt:
            curr = mkt['currency']
            price = mkt['price']

            # FX Conversion
            if curr == BASE_CURRENCY:
                rate = 1.0
            else:
                if curr not in fx_cache:
                    fx_cache[curr] = get_exchange_rate(curr, BASE_CURRENCY)
                rate = fx_cache[curr]

            val = row['quantity'] * price * rate
            total_market_value += val
            total_cost += row['cost_basis_local']

            allocation_data.append({
                'Market Value': val,
                'Sector': meta.get('sector') or 'Unknown',
                'Region': meta.get('region') or 'Unknown',
                'Asset Class': meta.get('asset_class') or 'Equity'
            })

    # 2. Cash Balance
    total_cash_base = pd.read_sql_query(
        "SELECT COALESCE(SUM(amount_local), 0) as total FROM transactions", conn
    ).iloc[0]['total']

    # 3. Income Totals
    income = get_income_and_costs()
    conn.close()

    return {
        "market_value": total_market_value,
        "cost_basis": total_cost,
        "cash": total_cash_base,
        "dividends": income['dividends'],
        "interest": income['interest'],
        "fees": income['fees'],
        "allocation": pd.DataFrame(allocation_data)
    }

data = load_summary_data()

# --- METRICS DISPLAY ---

# 1. Net Wealth Overview
styled_subheader("Net Equity Overview")
col1, col2, col3 = st.columns(3)

net_worth = data['market_value'] + data['cash']
total_gain = data['market_value'] - data['cost_basis']
total_return_pct = (data['market_value'] / data['cost_basis'] - 1) * 100 if data['cost_basis'] > 0 else 0

col1.metric("Total Net Equity", format_local(net_worth))
col2.metric("Stock Holdings", format_local(data['market_value']))
col3.metric("Cash & Margin", format_local(data['cash']), help="Negative value indicates margin usage.")

# 2. Performance & Growth
styled_subheader("Performance & Growth")
col4, col5, col6 = st.columns(3)

col4.metric("Unrealized Gain/Loss", format_local(total_gain), f"{format_local(total_return_pct, 2)}%", delta_color="normal")
col5.metric("Invested Capital (Cost Basis)", format_local(data['cost_basis']))

# 3. Income & Costs (Cash Flow)
styled_subheader("Cash Flow — All Time")
col6, col7, col8 = st.columns(3)

col6.metric("Total Dividends", format_local(data['dividends']), delta_color="normal")
col7.metric("Total Interest Paid", format_local(data['interest']), delta_color="inverse")
col8.metric("Total Fees Paid", format_local(data['fees']), delta_color="inverse")

st.divider()

# --- ALLOCATION CHARTS (Donut) ---
styled_subheader("Portfolio Allocation")
acol1, acol2 = st.columns(2)

df_alloc = data['allocation']
if not df_alloc.empty:
    with acol1:
        fig_sector = px.pie(
            df_alloc, values='Market Value', names='Sector',
            title='By Sector', hole=0.45,
            color_discrete_sequence=CHART_COLORS,
        )
        fig_sector.update_layout(**get_plotly_layout())
        fig_sector.update_traces(
            textfont=dict(color="#E6EDF3"),
            marker=dict(line=dict(color="#0E1117", width=2)),
        )
        st.plotly_chart(fig_sector, use_container_width=True)
    with acol2:
        fig_region = px.pie(
            df_alloc, values='Market Value', names='Region',
            title='By Region', hole=0.45,
            color_discrete_sequence=CHART_COLORS,
        )
        fig_region.update_layout(**get_plotly_layout())
        fig_region.update_traces(
            textfont=dict(color="#E6EDF3"),
            marker=dict(line=dict(color="#0E1117", width=2)),
        )
        st.plotly_chart(fig_region, use_container_width=True)
else:
    st.info("No allocation data available.")

st.divider()
st.markdown(
    '<p style="color: #8B949E; text-align: center; font-size: 0.9rem;">'
    'Use the sidebar to navigate to detailed views for Holdings, Dividends, Interest, and more.</p>',
    unsafe_allow_html=True,
)
