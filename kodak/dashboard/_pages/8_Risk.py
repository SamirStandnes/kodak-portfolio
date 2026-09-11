import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, COLORS, page_setup, format_pct,
    display_table, number_col, render_chart, load_valued_holdings,
)

page_setup("Risk & Concentration", "⚠️", "How concentrated the portfolio is by position, currency, sector and country.")

df_val = load_valued_holdings()
df_val = df_val[~df_val['is_nominal']].reset_index(drop=True)   # rights etc. carry no value

if df_val.empty:
    st.info("No holdings data available.")
    st.stop()

total_val = float(df_val['market_value_local'].sum())
df = df_val.rename(columns={
    'symbol': 'Symbol', 'market_value_local': 'Market Value', 'weight_pct': 'Weight %',
    'currency': 'Currency', 'sector': 'Sector', 'region': 'Region',
    'country': 'Country', 'asset_class': 'Asset Class',
})

# --- KEY METRICS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Positions", len(df))
col2.metric("Largest Position", format_pct(df.iloc[0]['Weight %'], 1), help=df.iloc[0]['Symbol'])
col3.metric("Top 5 Concentration", format_pct(df.head(5)['Weight %'].sum(), 1))
col4.metric("Top 10 Concentration", format_pct(df.head(10)['Weight %'].sum(), 1))

unpriced = int((~df_val['has_price']).sum())
if unpriced:
    st.caption(f"{unpriced} position(s) without a stored price are carried at cost basis. "
               "Nominal positions (rights with no price and no cost) are excluded.")

st.divider()

# --- SINGLE STOCK CONCENTRATION ---
st.subheader("Position Concentration")

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
    labels={'Weight %': 'Portfolio Weight (%)', 'Symbol': ''},
)
fig_conc.update_traces(hovertemplate="<b>%{y}</b><br>Weight: %{x:.2f}%<extra></extra>")
fig_conc.add_vline(x=10, line_dash='dash', line_color=COLORS['warning'],
                   annotation_text='10% threshold', annotation_position='top right')
fig_conc.update_layout(
    yaxis=dict(autorange='reversed'), hovermode='closest',
    xaxis_title='Portfolio Weight (%)', yaxis_title='',
    height=max(400, 24 * len(df_conc) + 120),
)
render_chart(fig_conc)

display_table(df_conc, {
    "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
    "Weight %": number_col("Weight %", fmt="%.1f%%"),
}, height=min(560, 40 * len(df_conc) + 60))

st.divider()


def exposure_section(title: str, column: str, chart_title: str):
    st.subheader(title)
    grouped = df.groupby(column)['Market Value'].sum().reset_index()
    grouped['Weight %'] = grouped['Market Value'] / total_val * 100
    grouped = grouped.sort_values('Market Value', ascending=False)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.pie(grouped, values='Market Value', names=column,
                     color_discrete_sequence=palette, hole=0.4, title=chart_title)
        fig.update_traces(
            textposition='inside', texttemplate='%{percent:.1%}',
            marker=dict(line=dict(color=COLORS['bg'], width=2)),
            hovertemplate=f"<b>%{{label}}</b><br>%{{value:,.0f}} {BASE_CURRENCY}<br>%{{percent:.1%}}<extra></extra>")
        fig.update_layout(hovermode='closest', uniformtext_minsize=11, uniformtext_mode='hide',
                          legend=dict(orientation='v', x=1.02, y=0.5), margin=dict(l=10, r=10, t=48, b=10))
        render_chart(fig)
    with c2:
        display_table(grouped, {
            "Market Value": number_col(f"Value ({BASE_CURRENCY})"),
            "Weight %": number_col("Weight %", fmt="%.1f%%"),
        }, height=300)


exposure_section("Currency Exposure", 'Currency', 'Currency Split')
st.divider()
exposure_section("Sector Exposure", 'Sector', 'Sector Split')
st.divider()
exposure_section("Geographic Exposure", 'Country', 'Country Split')
