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
    display_aggrid, render_chart, load_valued_holdings, price_freshness,
)
from kodak.shared.db import get_db_connection, query_df
from kodak.shared.calculations import get_price_history

page_setup("Holdings", "🏦", "Every open position valued at the latest stored price, with cost basis, return and weight.")


@st.cache_data(ttl=CACHE_TTL)
def load_price_history(instrument_id: int) -> pd.DataFrame:
    return get_price_history(instrument_id)


@st.cache_data(ttl=CACHE_TTL)
def load_trades(instrument_id: int) -> pd.DataFrame:
    """BUY/SELL executions for one instrument (price in the asset's currency)."""
    with get_db_connection() as conn:
        df = query_df(
            "SELECT date, type, quantity, price FROM transactions "
            "WHERE instrument_id = ? AND type IN ('BUY', 'SELL') AND price > 0 ORDER BY date",
            conn, params=(int(instrument_id),))
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['date'].astype(str).str[:10], format='%Y-%m-%d')
    return df


df_val = load_valued_holdings()
latest_date, prev_date = price_freshness(df_val)

total_val = float(df_val['market_value_local'].sum())
change_value = float(df_val['day_change_local'].sum())
change_pct = (change_value / (total_val - change_value) * 100) if (total_val - change_value) > 0 else 0
unpriced = int((~df_val['has_price']).sum()) if not df_val.empty else 0

# --- KEY METRICS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Equity Value", format_local(total_val))

if not df_val.empty:
    col2.metric(
        f"Since {prev_date}" if prev_date else "Change",
        format_local(change_value),
        format_pct(change_pct, 2, sign=True),
        help=(f"Move between the two most recent stored prices ({prev_date} → {latest_date}). "
              "Prices are refreshed on demand, so this is not necessarily one trading day."),
    )
    top5_pct = df_val.head(5)['weight_pct'].sum()
    col3.metric("Top 5 Concentration", format_pct(top5_pct, 1),
                help="Share of the portfolio in your 5 largest positions")
    col4.metric("Positions", len(df_val),
                help=f"{unpriced} position(s) have no stored price and are carried at cost" if unpriced else None)

if latest_date:
    st.caption(f"Prices as of **{latest_date}**")

st.divider()

# --- CONCENTRATION BAR ---
if not df_val.empty:
    st.subheader("Position Sizes")
    df_bar = df_val.head(15)
    fig = px.bar(
        df_bar, x='market_value_local', y='symbol', orientation='h',
        color='return_pct',
        color_continuous_scale=[COLORS['negative'], COLORS['neutral'], COLORS['positive']],
        color_continuous_midpoint=0,
        labels={'market_value_local': f'Market Value ({BASE_CURRENCY})', 'symbol': '', 'return_pct': 'Return %'},
    )
    fig.update_traces(hovertemplate=(
        "<b>%{y}</b><br>"
        f"Market Value: %{{x:,.0f}} {BASE_CURRENCY}<br>"
        "Return: %{marker.color:+.2f}%<extra></extra>"
    ))
    fig.update_layout(
        yaxis=dict(autorange='reversed'), hovermode='closest',
        xaxis_title=f'Market Value ({BASE_CURRENCY})', yaxis_title='',
    )
    render_chart(fig)

st.divider()

# --- HOLDINGS TABLE ---
st.subheader("All Holdings")
# Numbers first (they fit the grid width without scrolling); classification
# columns follow and are reachable by scrolling right. The name shows as a
# tooltip on the symbol.
table = pd.DataFrame({
    "Symbol": df_val['symbol'],
    "Name": df_val['name'],
    "Quantity": df_val['quantity'],
    "Price": df_val['price'],
    "Ccy": df_val['currency'],
    "Market Value": df_val['market_value_local'].round(),
    "Cost Basis": df_val['cost_basis_local'].round(),
    "Change %": df_val['day_change_pct'],
    "Change Δ": df_val['day_change_local'].round(),
    "Gain/Loss": df_val['gain_local'].round(),
    "Return %": df_val['return_pct'],
    "Weight %": df_val['weight_pct'],
    "Sector": df_val['sector'],
    "Region": df_val['region'],
    "Country": df_val['country'],
    "Type": df_val['asset_class'],
})
display_aggrid(
    table,
    columns={
        "Symbol":       {"width": 95, "tooltip_field": "Name"},
        "Name":         {"hide": True},
        "Quantity":     {"label": "Qty", "type": "quantity", "decimals": 4, "width": 80},
        "Price":        {"type": "number", "decimals": 2, "width": 90},
        "Ccy":          {"width": 60},
        "Market Value": {"label": f"Value ({BASE_CURRENCY})", "type": "currency", "decimals": 0, "width": 115},
        "Cost Basis":   {"label": "Cost", "type": "currency", "decimals": 0, "width": 105},
        "Change %":     {"label": "Chg %", "type": "percent",  "decimals": 2, "color_signed": True, "width": 85},
        "Change Δ":     {"label": f"Chg ({BASE_CURRENCY})", "type": "currency", "decimals": 0, "color_signed": True, "width": 105},
        "Gain/Loss":    {"label": "Gain / Loss", "type": "currency", "decimals": 0, "color_signed": True, "width": 110},
        "Return %":     {"label": "Return", "type": "percent",  "decimals": 1, "color_signed": True, "width": 85},
        "Weight %":     {"label": "Weight", "type": "progress", "max": 100, "decimals": 1, "width": 110},
        "Sector":       {"width": 150},
        "Region":       {"width": 130},
        "Country":      {"width": 130},
        "Type":         {"width": 80},
    },
    pin_left=["Symbol"],
    height=900,
    totals={
        "Symbol": "Total", "Market Value": round(total_val), "Cost Basis": round(df_val['cost_basis_local'].sum()),
        "Change Δ": round(change_value), "Gain/Loss": round(df_val['gain_local'].sum()),
        "Change %": change_pct,
        "Return %": (total_val / df_val['cost_basis_local'].sum() - 1) * 100 if df_val['cost_basis_local'].sum() else None,
        "Weight %": 100.0,
    },
)
st.caption(f"Market Value, Cost Basis, Change Δ and Gain/Loss are in {BASE_CURRENCY}; Price is in the asset's currency.")

st.divider()

# --- PRICE HISTORY ---
st.subheader("Price History")
priced = df_val[df_val['has_price']]
if priced.empty:
    st.info("No stored price history yet.")
else:
    options = priced['symbol'].tolist()
    chosen = st.selectbox("Instrument", options, label_visibility="collapsed")
    row = priced[priced['symbol'] == chosen].iloc[0]
    hist = load_price_history(int(row['instrument_id']))
    if len(hist) < 2:
        st.info("Only one stored price for this instrument so far.")
    else:
        first_close, last_close = hist['close'].iloc[0], hist['close'].iloc[-1]
        period_pct = (last_close / first_close - 1) * 100 if first_close else 0
        hcol1, hcol2, hcol3 = st.columns(3)
        hcol1.metric("Last Close", f"{format_local(last_close, 2)} {row['currency']}")
        hcol2.metric(f"Since {hist['date'].iloc[0]:%d %b %Y}", format_pct(period_pct, 1, sign=True))
        hcol3.metric("Held", format_local(row['quantity'], 0 if float(row['quantity']).is_integer() else 2))

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist['date'], y=hist['close'], mode='lines', name='Close',
            line=dict(color=COLORS['primary'], width=2),
            hovertemplate=f"%{{y:,.2f}} {row['currency']}<extra>Close</extra>",
        ))
        trades = load_trades(int(row['instrument_id']))
        if not trades.empty:
            window = trades[trades['date'] >= hist['date'].iloc[0]]
            for t_type, color, symbol_mark in (("BUY", COLORS['positive'], "triangle-up"),
                                              ("SELL", COLORS['negative'], "triangle-down")):
                sub = window[window['type'] == t_type]
                if sub.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=sub['date'], y=sub['price'], mode='markers', name=t_type.title(),
                    marker=dict(color=color, size=11, symbol=symbol_mark, line=dict(width=1, color=COLORS['bg'])),
                    customdata=sub['quantity'].abs(),
                    hovertemplate=f"{t_type.title()} %{{customdata:,.0f}} @ %{{y:,.2f}} {row['currency']}<extra></extra>",
                ))
        fig.update_layout(
            hovermode='x unified', yaxis_title=row['currency'], xaxis_title='',
            legend=dict(orientation='h', y=1.08, x=0),
            margin=dict(l=40, r=20, t=40, b=40),
        )
        render_chart(fig)
