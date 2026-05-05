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
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local,
    display_table, number_col, apply_plotly_theme, convert_to_base,
)
from kodak.shared.db import get_connection, query_df
from kodak.shared.calculations import get_holdings

page_setup("Risk & Concentration", "🎯")


@st.cache_data(ttl=CACHE_TTL)
def load_risk_data():
    conn = get_connection()
    df_holdings = get_holdings()

    prices = query_df('''
        SELECT mp.instrument_id, mp.close, i.currency, COALESCE(i.symbol, i.isin) as symbol,
               i.sector, i.region, i.country, i.asset_class
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
            'symbol': row['symbol'], 'sector': row['sector'],
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

        val = row['quantity'] * convert_to_base(mkt['price'], mkt['currency'], fx_cache)
        total_val += val

        data.append({
            'Symbol': mkt['symbol'],
            'Market Value': val,
            'Currency': mkt['currency'],
            'Sector': mkt['sector'] or 'Unknown',
            'Region': mkt['region'] or 'Unknown',
            'Country': mkt['country'] or 'Unknown',
            'Asset Class': mkt['asset_class'] or 'Unknown',
        })

    df = pd.DataFrame(data).sort_values('Market Value', ascending=False)
    if not df.empty:
        df['Weight %'] = (df['Market Value'] / total_val) * 100
    return df, total_val


df, total_val = load_risk_data()

if df.empty:
    st.info("No holdings data available.")
    st.stop()

# --- KEY METRICS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Positions", len(df))

top1_pct = df.iloc[0]['Weight %'] if len(df) > 0 else 0
top5_pct = df.head(5)['Weight %'].sum()
top10_pct = df.head(10)['Weight %'].sum()

col2.metric("Largest Position", f"{top1_pct:.1f}%", help=df.iloc[0]['Symbol'])
col3.metric("Top 5 Concentration", f"{top5_pct:.1f}%")
col4.metric("Top 10 Concentration", f"{top10_pct:.1f}%")

st.divider()

# --- SINGLE STOCK CONCENTRATION ---
st.subheader("Position Concentration")

# Highlight positions > 10%
df_conc = df[['Symbol', 'Market Value', 'Weight %']].copy()
df_conc['Status'] = df_conc['Weight %'].apply(
    lambda w: '🔴 High' if w > 15 else ('🟡 Elevated' if w > 10 else '🟢 OK')
)

palette = [COLORS['primary'], COLORS['positive'], COLORS['warning'],
           COLORS['purple'], COLORS['light_blue'], COLORS['negative'], COLORS['neutral']]

fig_conc = px.bar(
    df_conc, x='Weight %', y='Symbol', orientation='h',
    color='Weight %',
    color_continuous_scale=[[0, COLORS['positive']], [0.5, COLORS['warning']], [1, COLORS['negative']]],
)
fig_conc.update_layout(yaxis=dict(autorange='reversed'), xaxis_title='Portfolio Weight (%)')
fig_conc.add_vline(x=10, line_dash='dash', line_color=COLORS['warning'],
                   annotation_text='10% threshold', annotation_position='top right')
apply_plotly_theme(fig_conc)
st.plotly_chart(fig_conc, use_container_width=True)

display_table(df_conc, {
    "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
    "Weight %": number_col("Weight %", fmt="%.1f%%"),
})

st.divider()

# --- CURRENCY CONCENTRATION ---
st.subheader("Currency Exposure")
df_curr = df.groupby('Currency')['Market Value'].sum().reset_index()
df_curr['Weight %'] = (df_curr['Market Value'] / total_val) * 100
df_curr = df_curr.sort_values('Market Value', ascending=False)

ccol1, ccol2 = st.columns(2)
with ccol1:
    fig_curr = px.pie(df_curr, values='Market Value', names='Currency',
                      color_discrete_sequence=palette, hole=0.4, title='Currency Split')
    apply_plotly_theme(fig_curr)
    st.plotly_chart(fig_curr, use_container_width=True)

with ccol2:
    display_table(df_curr, {
        "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
        "Weight %": number_col("Weight %", fmt="%.1f%%"),
    }, height=300)

st.divider()

# --- SECTOR CONCENTRATION ---
st.subheader("Sector Exposure")
df_sector = df.groupby('Sector')['Market Value'].sum().reset_index()
df_sector['Weight %'] = (df_sector['Market Value'] / total_val) * 100
df_sector = df_sector.sort_values('Market Value', ascending=False)

scol1, scol2 = st.columns(2)
with scol1:
    fig_sec = px.pie(df_sector, values='Market Value', names='Sector',
                     color_discrete_sequence=palette, hole=0.4, title='Sector Split')
    apply_plotly_theme(fig_sec)
    st.plotly_chart(fig_sec, use_container_width=True)

with scol2:
    display_table(df_sector, {
        "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
        "Weight %": number_col("Weight %", fmt="%.1f%%"),
    }, height=300)

st.divider()

# --- GEOGRAPHIC CONCENTRATION ---
st.subheader("Geographic Exposure")
df_geo = df.groupby('Country')['Market Value'].sum().reset_index()
df_geo['Weight %'] = (df_geo['Market Value'] / total_val) * 100
df_geo = df_geo.sort_values('Market Value', ascending=False)

gcol1, gcol2 = st.columns(2)
with gcol1:
    fig_geo = px.pie(df_geo, values='Market Value', names='Country',
                     color_discrete_sequence=palette, hole=0.4, title='Country Split')
    apply_plotly_theme(fig_geo)
    st.plotly_chart(fig_geo, use_container_width=True)

with gcol2:
    display_table(df_geo, {
        "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
        "Weight %": number_col("Weight %", fmt="%.1f%%"),
    }, height=300)
