import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.shared.db import get_connection
from kodak.shared.calculations import get_holdings
from kodak.shared.market_data import get_latest_prices, get_exchange_rate
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Holdings", page_icon="🏦", layout="wide")
apply_theme()

page_header("Current Holdings", "Positions and market values")

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_holdings_data():
    conn = get_connection()
    df_holdings = get_holdings()

    # Get latest prices and metadata
    prices = pd.read_sql_query('''
        SELECT mp.instrument_id, mp.close, i.currency, COALESCE(i.symbol, i.isin) as symbol,
               i.name, i.sector, i.region, i.country, i.asset_class
        FROM market_prices mp
        JOIN instruments i ON mp.instrument_id = i.id
        WHERE (mp.instrument_id, mp.date) IN (
            SELECT instrument_id, MAX(date)
            FROM market_prices
            GROUP BY instrument_id
        )
    ''', conn)

    conn.close()

    price_map = {}
    for _, row in prices.iterrows():
        price_map[row['instrument_id']] = {
            'price': row['close'],
            'currency': row['currency'],
            'name': row['name'],
            'sector': row['sector'],
            'region': row['region'],
            'country': row['country'],
            'asset_class': row['asset_class']
        }

    data = []
    fx_cache = {}
    total_val = 0

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        mkt = price_map.get(inst_id)

        if not mkt:
            continue # Skip unpriced (handled by gap check)

        price = 0
        curr = BASE_CURRENCY

        if mkt:
            price = mkt['price']
            curr = mkt['currency']

        # FX Conversion
        if curr == BASE_CURRENCY:
            rate = 1.0
        else:
            if curr not in fx_cache:
                fx_cache[curr] = get_exchange_rate(curr, BASE_CURRENCY)
            rate = fx_cache[curr]

        market_val_nok = row['quantity'] * price * rate
        cost_basis = row['cost_basis_local']
        gain = market_val_nok - cost_basis
        ret_pct = (market_val_nok / cost_basis - 1) * 100 if cost_basis > 0 else 0

        total_val += market_val_nok

        data.append({
            "Symbol": row['symbol'],
            "Quantity": row['quantity'],
            "Sector": mkt['sector'],
            "Region": mkt['region'],
            "Country": mkt['country'],
            "Type": mkt['asset_class'],
            "Market Value": market_val_nok,
            "Gain/Loss": gain,
            "Return %": ret_pct
        })

    df = pd.DataFrame(data)

    # Calculate Weight
    if not df.empty:
        df['Weight %'] = (df['Market Value'] / total_val) * 100
        # Round values for cleaner display but keep as floats for NumberColumn to handle
        df['Quantity'] = df['Quantity'].round(0)
        df['Market Value'] = df['Market Value'].round(0)
        df['Gain/Loss'] = df['Gain/Loss'].round(0)

    return df.sort_values('Market Value', ascending=False)

df = load_holdings_data()

# Summary Metrics for this page
st.metric("Total Equity Value", format_local(df['Market Value'].sum()))

# Styling the dataframe
st.dataframe(
    df,
    column_config={
        "Quantity": st.column_config.NumberColumn(format="localized"),
        "Market Value": st.column_config.NumberColumn(f"Market Value ({BASE_CURRENCY})", format="localized"),
        "Gain/Loss": st.column_config.NumberColumn(f"Gain/Loss ({BASE_CURRENCY})", format="localized"),
        "Return %": st.column_config.NumberColumn(format="%.1f%%"),
        "Weight %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
    },
    use_container_width=True,
    hide_index=True,
    height=600
)
