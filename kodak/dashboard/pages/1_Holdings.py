import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, page_setup, format_local,
    display_table, number_col, convert_to_base,
)
from kodak.shared.db import get_connection
from kodak.shared.calculations import get_holdings

page_setup("Holdings", "🏦")


@st.cache_data(ttl=CACHE_TTL)
def load_holdings_data():
    conn = get_connection()
    df_holdings = get_holdings()

    prices = pd.read_sql_query('''
        SELECT mp.instrument_id, mp.close, i.currency, COALESCE(i.symbol, i.isin) as symbol,
               i.name, i.sector, i.region, i.country, i.asset_class
        FROM market_prices mp
        JOIN instruments i ON mp.instrument_id = i.id
        WHERE (mp.instrument_id, mp.date) IN (
            SELECT instrument_id, MAX(date) FROM market_prices GROUP BY instrument_id
        )
    ''', conn)
    conn.close()

    price_map = {}
    for _, row in prices.iterrows():
        price_map[row['instrument_id']] = {
            'price': row['close'], 'currency': row['currency'],
            'name': row['name'], 'sector': row['sector'],
            'region': row['region'], 'country': row['country'],
            'asset_class': row['asset_class'],
        }

    data = []
    fx_cache = {}
    total_val = 0

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        mkt = price_map.get(inst_id)
        if not mkt:
            continue

        price = mkt['price']
        curr = mkt['currency']
        market_val = row['quantity'] * convert_to_base(price, curr, fx_cache)
        cost_basis = row['cost_basis_local']
        gain = market_val - cost_basis
        ret_pct = (market_val / cost_basis - 1) * 100 if cost_basis > 0 else 0

        total_val += market_val

        data.append({
            "Symbol": row['symbol'],
            "Quantity": round(row['quantity']),
            "Sector": mkt['sector'],
            "Region": mkt['region'],
            "Country": mkt['country'],
            "Type": mkt['asset_class'],
            "Market Value": round(market_val),
            "Gain/Loss": round(gain),
            "Return %": ret_pct,
        })

    df = pd.DataFrame(data)
    if not df.empty:
        df['Weight %'] = (df['Market Value'] / total_val) * 100
    return df.sort_values('Market Value', ascending=False)


df = load_holdings_data()

st.metric("Total Equity Value", format_local(df['Market Value'].sum()))

display_table(df, {
    "Quantity": number_col("Quantity"),
    "Market Value": number_col(f"Market Value ({BASE_CURRENCY})"),
    "Gain/Loss": number_col(f"Gain/Loss ({BASE_CURRENCY})"),
    "Return %": number_col("Return %", fmt="%.1f%%"),
    "Weight %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
})
