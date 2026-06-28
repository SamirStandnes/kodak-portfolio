import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
from kodak.dashboard.common import (
    BASE_CURRENCY, CACHE_TTL, COLORS, page_setup, format_local,
    display_table, display_aggrid, number_col, apply_plotly_theme, convert_to_base,
)
from kodak.shared.db import get_connection, query_df
from kodak.shared.calculations import get_holdings

page_setup("Holdings", "🏦")


@st.cache_data(ttl=CACHE_TTL)
def load_holdings_data():
    conn = get_connection()
    df_holdings = get_holdings()

    # Latest close + previous close per instrument (for daily change).
    # Use query_df (cursor-based) — pd.read_sql_query bypasses the Heroku
    # SQL translation layer and crashes on Postgres.
    prices = query_df('''
        WITH ranked AS (
            SELECT instrument_id, date, close,
                   ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY date DESC) AS rn
            FROM market_prices
        )
        SELECT
            latest.instrument_id, latest.close AS close, latest.date AS price_date,
            prev.close AS prev_close,
            i.currency, COALESCE(i.symbol, i.isin) AS symbol,
            i.name, i.sector, i.region, i.country, i.asset_class
        FROM ranked AS latest
        LEFT JOIN ranked AS prev
          ON latest.instrument_id = prev.instrument_id AND prev.rn = 2
        JOIN instruments i ON latest.instrument_id = i.id
        WHERE latest.rn = 1
    ''', conn)

    price_map = {}
    for _, row in prices.iterrows():
        prev = row['prev_close']
        day_change_pct = (
            (row['close'] / prev - 1) * 100
            if prev and prev > 0 and pd.notna(prev) else None
        )
        price_map[row['instrument_id']] = {
            'price': row['close'], 'currency': row['currency'],
            'name': row['name'], 'sector': row['sector'],
            'region': row['region'], 'country': row['country'],
            'asset_class': row['asset_class'],
            'day_change_pct': day_change_pct,
        }

    # Instrument metadata for ALL instruments — used to label holdings that
    # have no current market_prices row (the price join above excludes them).
    meta = query_df(
        'SELECT id, sector, region, country, asset_class FROM instruments', conn
    )
    meta_map = meta.set_index('id').to_dict('index')
    conn.close()

    data = []
    fx_cache = {}
    total_val = 0
    total_day_change_value = 0  # day change in base currency

    for _, row in df_holdings.iterrows():
        inst_id = row['instrument_id']
        mkt = price_map.get(inst_id)
        m = meta_map.get(inst_id, {})
        cost_basis = row['cost_basis_local']

        if mkt:
            price = mkt['price']
            curr = mkt['currency']
            market_val = row['quantity'] * convert_to_base(price, curr, fx_cache)
            sector, region = mkt['sector'], mkt['region']
            country, asset_class = mkt['country'], mkt['asset_class']
            day_pct = mkt['day_change_pct']
        else:
            # No current market price (illiquid/private holding, or prices not
            # yet populated in this DB — e.g. right after a deploy drops &
            # recreates market_prices, before the price cron repopulates).
            # Carry the position at cost basis so it still appears instead of
            # silently vanishing and leaving an empty, column-less DataFrame
            # that crashes sort_values('Market Value'). Self-heals to live
            # prices once market_prices is populated.
            market_val = cost_basis
            sector, region = m.get('sector'), m.get('region')
            country, asset_class = m.get('country'), m.get('asset_class')
            day_pct = None

        gain = market_val - cost_basis
        ret_pct = (market_val / cost_basis - 1) * 100 if cost_basis > 0 else 0
        day_value = market_val * (day_pct / 100) if day_pct is not None else 0

        total_val += market_val
        total_day_change_value += day_value

        data.append({
            "Symbol": row['symbol'],
            "Quantity": round(row['quantity']),
            "Sector": sector,
            "Region": region,
            "Country": country,
            "Type": asset_class,
            "Market Value": round(market_val),
            "Day %": day_pct,
            "Day Δ": round(day_value),
            "Gain/Loss": round(gain),
            "Return %": ret_pct,
        })

    columns = ["Symbol", "Quantity", "Sector", "Region", "Country", "Type",
               "Market Value", "Day %", "Day Δ", "Gain/Loss", "Return %", "Weight %"]
    df = pd.DataFrame(data, columns=columns)
    if not df.empty:
        df['Weight %'] = (df['Market Value'] / total_val) * 100 if total_val else 0
    return df.sort_values('Market Value', ascending=False), total_val, total_day_change_value


df, total_val, total_day_change_value = load_holdings_data()

# --- KEY METRICS ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Equity Value", format_local(df['Market Value'].sum()))

if not df.empty:
    day_change_pct_total = (total_day_change_value / (total_val - total_day_change_value)) * 100 if (total_val - total_day_change_value) > 0 else 0
    col2.metric(
        "Today",
        format_local(total_day_change_value),
        f"{day_change_pct_total:+.2f}%",
        help="Daily change since previous close, in base currency",
    )
    top5_val = df.head(5)['Market Value'].sum()
    top5_pct = (top5_val / total_val) * 100 if total_val > 0 else 0
    col3.metric("Top 5 Concentration", f"{top5_pct:.1f}%",
                help="Percentage of portfolio in your 5 largest positions")
    col4.metric("Positions", len(df))

st.divider()

# --- CONCENTRATION BAR ---
if not df.empty:
    st.subheader("Position Sizes")
    df_bar = df.head(15).copy()
    fig = px.bar(
        df_bar, x='Market Value', y='Symbol', orientation='h',
        color='Return %',
        color_continuous_scale=['#E74C3C', '#95A5A6', '#27AE60'],
        color_continuous_midpoint=0,
        labels={'Market Value': f'Market Value ({BASE_CURRENCY})', 'Symbol': '', 'Return %': 'Return'},
    )
    fig.update_traces(hovertemplate=(
        "<b>%{y}</b><br>"
        f"Market Value: %{{x:,.0f}} {BASE_CURRENCY}<br>"
        "Return: %{marker.color:+.2f}%<extra></extra>"
    ))
    apply_plotly_theme(fig)
    fig.update_layout(
        yaxis=dict(autorange='reversed'),
        hovermode='closest',
        xaxis_title=f'Market Value ({BASE_CURRENCY})',
        yaxis_title='',
    )
    st.plotly_chart(fig, use_container_width=True, theme=None)

st.divider()

# --- HOLDINGS TABLE ---
st.subheader("All Holdings")
display_aggrid(
    df,
    columns={
        "Symbol":       {"width": 110},
        "Quantity":     {"type": "number", "decimals": 0, "width": 100},
        "Sector":       {"width": 140},
        "Region":       {"width": 110},
        "Country":      {"width": 110},
        "Type":         {"width": 100},
        "Market Value": {"type": "currency", "decimals": 0, "width": 140},
        "Day %":        {"type": "percent",  "decimals": 2, "color_signed": True, "width": 100},
        "Day Δ":        {"type": "currency", "decimals": 0, "color_signed": True, "width": 110},
        "Gain/Loss":    {"type": "currency", "decimals": 0, "color_signed": True, "width": 130},
        "Return %":     {"type": "percent",  "decimals": 1, "color_signed": True, "width": 110},
        "Weight %":     {"type": "progress", "max": 100, "width": 140},
    },
    pin_left=["Symbol"],
    height=560,
)
