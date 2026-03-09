"""
Heroku Streamlit Dashboard - Main Entry Point

Cloud-ready version of the Kodak portfolio dashboard.
Uses PostgreSQL and includes password protection.
"""
import streamlit as st
import os

# --- COLOR PALETTE (matches local dashboard) ---
COLORS = {
    "primary": "#4A90D9",
    "positive": "#27AE60",
    "negative": "#E74C3C",
    "warning": "#F39C12",
    "purple": "#8E44AD",
    "neutral": "#95A5A6",
    "light_blue": "#5DADE2",
    "text_muted": "#AAB2BD",
}

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#FAFAFA", size=13),
    margin=dict(l=40, r=40, t=50, b=40),
    hovermode="x unified",
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
)

def apply_plotly_theme(fig):
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig

# --- JARVIS STATIC API ---
# Generates holdings.json and summary.json on startup, served as static files.
# Jarvis fetches: https://<app>.herokuapp.com/app/static/api/holdings.json?token=<password>
@st.cache_resource(ttl=300)
def _generate_static_api():
    try:
        import heroku.setup_adapters  # noqa: F401
        import json, pandas as pd
        from pathlib import Path
        from kodak.shared.calculations import get_holdings, get_income_and_costs
        from kodak.shared.market_data import get_exchange_rate
        from kodak.shared.utils import load_config
        from kodak.shared.db import get_db_connection

        cfg = load_config()
        base = cfg.get("base_currency", "NOK")
        static_dir = Path(__file__).parent / "static" / "api"
        static_dir.mkdir(parents=True, exist_ok=True)

        # Holdings
        with get_db_connection() as conn:
            df_h = get_holdings()
            prices = pd.read_sql_query("""
                SELECT mp.instrument_id, mp.close, i.currency, i.symbol, i.name,
                       i.sector, i.region, i.country, i.asset_class
                FROM market_prices mp JOIN instruments i ON mp.instrument_id = i.id
                WHERE (mp.instrument_id, mp.date) IN (
                    SELECT instrument_id, MAX(date) FROM market_prices GROUP BY instrument_id
                )
            """, conn)

        pm = {r["instrument_id"]: r for _, r in prices.iterrows()}
        fx, rows, total = {}, [], 0
        for _, r in df_h.iterrows():
            m = pm.get(r["instrument_id"])
            if m is None: continue
            curr = m["currency"]
            rate = 1.0 if curr == base else fx.setdefault(curr, get_exchange_rate(curr, base))
            val = r["quantity"] * m["close"] * rate
            cost = r["cost_basis_local"]
            total += val
            rows.append({"symbol": r["symbol"], "quantity": round(float(r["quantity"]), 4),
                "sector": m["sector"], "region": m["region"], "country": m["country"],
                "asset_class": m["asset_class"], "currency": curr,
                "price": round(float(m["close"]), 4), "market_value": round(val, 2),
                "cost_basis": round(cost, 2), "gain_loss": round(val - cost, 2),
                "return_pct": round((val / cost - 1) * 100, 2) if cost > 0 else 0})
        for row in rows:
            row["weight_pct"] = round(row["market_value"] / total * 100, 2) if total > 0 else 0
        rows.sort(key=lambda x: x["market_value"], reverse=True)
        holdings_payload = {"base_currency": base, "total_market_value": round(total, 2), "holdings": rows}
        (static_dir / "holdings.json").write_text(json.dumps(holdings_payload, indent=2))

        # Summary
        income = get_income_and_costs()
        summary_payload = {"base_currency": base,
            "dividends": round(float(income["dividends"]), 2),
            "interest": round(float(income["interest"]), 2),
            "fees": round(float(income["fees"]), 2)}
        (static_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2))
    except Exception:
        pass

_generate_static_api()

# --- JARVIS API ---
# Serves portfolio data as JSON for Jarvis without requiring a browser session.
# Usage: GET /?jarvis=1&token=<DASHBOARD_PASSWORD>&resource=holdings|summary
_qp = st.query_params
if _qp.get("jarvis") == "1" and _qp.get("token") == os.environ.get("DASHBOARD_PASSWORD", ""):
    import heroku.setup_adapters  # noqa: F401
    import json
    import pandas as pd
    from kodak.shared.calculations import get_holdings, get_income_and_costs
    from kodak.shared.market_data import get_exchange_rate
    from kodak.shared.utils import load_config

    st.set_page_config(page_title="Kodak API", layout="wide")

    _cfg = load_config()
    _base = _cfg.get("base_currency", "NOK")
    _resource = _qp.get("resource", "holdings")

    if _resource == "holdings":
        from kodak.shared.db import get_db_connection
        with get_db_connection() as _conn:
            _df_h = get_holdings()
            _prices = pd.read_sql_query("""
                SELECT mp.instrument_id, mp.close, i.currency, i.symbol, i.name,
                       i.sector, i.region, i.country, i.asset_class
                FROM market_prices mp
                JOIN instruments i ON mp.instrument_id = i.id
                WHERE (mp.instrument_id, mp.date) IN (
                    SELECT instrument_id, MAX(date) FROM market_prices GROUP BY instrument_id
                )
            """, _conn)

        _pm = {r["instrument_id"]: r for _, r in _prices.iterrows()}
        _fx, _rows, _total = {}, [], 0

        for _, _r in _df_h.iterrows():
            _m = _pm.get(_r["instrument_id"])
            if _m is None:
                continue
            _curr = _m["currency"]
            _rate = 1.0 if _curr == _base else _fx.setdefault(_curr, get_exchange_rate(_curr, _base))
            _val = _r["quantity"] * _m["close"] * _rate
            _cost = _r["cost_basis_local"]
            _total += _val
            _rows.append({
                "symbol": _r["symbol"],
                "quantity": round(float(_r["quantity"]), 4),
                "sector": _m["sector"],
                "region": _m["region"],
                "country": _m["country"],
                "asset_class": _m["asset_class"],
                "currency": _curr,
                "price": round(float(_m["close"]), 4),
                "market_value": round(_val, 2),
                "cost_basis": round(_cost, 2),
                "gain_loss": round(_val - _cost, 2),
                "return_pct": round((_val / _cost - 1) * 100, 2) if _cost > 0 else 0,
            })

        for _row in _rows:
            _row["weight_pct"] = round(_row["market_value"] / _total * 100, 2) if _total > 0 else 0

        _rows.sort(key=lambda x: x["market_value"], reverse=True)
        _payload = {"base_currency": _base, "total_market_value": round(_total, 2), "holdings": _rows}

    elif _resource == "summary":
        _income = get_income_and_costs()
        _payload = {
            "base_currency": _base,
            "dividends": round(float(_income["dividends"]), 2),
            "interest": round(float(_income["interest"]), 2),
            "fees": round(float(_income["fees"]), 2),
        }
    else:
        _payload = {"error": f"Unknown resource: {_resource}. Use holdings or summary."}

    st.code(json.dumps(_payload, indent=2), language="json")
    st.stop()

# --- PASSWORD AUTHENTICATION ---
def check_password():
    """Returns True if the user has entered the correct password."""

    if st.session_state.get("password_correct"):
        return True

    st.set_page_config(page_title="Kodak Portfolio", page_icon="📈", layout="centered")

    # Hide default Streamlit chrome for a clean login screen
    st.markdown("""
        <style>
        #MainMenu, header, footer {visibility: hidden;}
        .block-container {
            max-width: 420px;
            padding-top: 8vh;
        }
        /* Hide "Press Enter to submit" tooltip above input */
        [data-testid="InputInstructions"],
        .stTextInput [data-testid="InputInstructions"],
        .stForm [data-testid="InputInstructions"] {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            overflow: hidden !important;
        }
        /* Make the submit button full-width and larger for mobile */
        .stForm [data-testid="stFormSubmitButton"] button {
            width: 100%;
            padding: 0.6rem 1rem;
            font-size: 1.1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("Kodak Portfolio")
    st.caption("Enter your password to continue")

    with st.form("login_form"):
        password = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        submitted = st.form_submit_button("Log in", use_container_width=True, type="primary")

    if submitted:
        if password == os.environ.get("DASHBOARD_PASSWORD", ""):
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    return False


# --- MAIN APPLICATION ---
if check_password():
    # Initialize adapters BEFORE importing kodak modules
    import heroku.setup_adapters  # noqa: F401

    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    from kodak.shared.db import get_db_connection
    from kodak.shared.calculations import (
        get_holdings, get_income_and_costs,
        get_dividend_details, get_dividend_forecast,
        get_interest_details,
        get_fee_details, get_fee_analysis, get_platform_fees,
        get_fx_performance_detailed,
        get_total_xirr, get_yearly_equity_curve, get_yearly_contribution
    )
    from kodak.shared.market_data import get_exchange_rate
    from kodak.shared.utils import load_config, format_local

    # --- CONFIGURATION ---
    config = load_config()
    BASE_CURRENCY = config.get('base_currency', 'NOK')
    CACHE_TTL = 300

    PALETTE = [COLORS['primary'], COLORS['positive'], COLORS['warning'],
               COLORS['purple'], COLORS['light_blue'], COLORS['negative'], COLORS['neutral']]

    def convert_to_base(amount, currency, fx_cache):
        if currency == BASE_CURRENCY:
            return amount
        if currency not in fx_cache:
            fx_cache[currency] = get_exchange_rate(currency, BASE_CURRENCY)
        return amount * fx_cache[currency]

    st.set_page_config(
        page_title=f"Kodak Portfolio ({BASE_CURRENCY})",
        page_icon="📈",
        layout="wide"
    )

    # Style sidebar navigation like native Streamlit pages
    st.markdown("""
        <style>
        /* Navigation button styling */
        div[data-testid="stSidebar"] button[kind="secondary"] {
            background-color: transparent;
            border: none;
            text-align: left;
            padding: 0.5rem 1rem;
            width: 100%;
            font-weight: normal;
        }
        div[data-testid="stSidebar"] button[kind="secondary"]:hover {
            background-color: rgba(151, 166, 195, 0.15);
            border: none;
        }
        div[data-testid="stSidebar"] button[kind="secondary"]:focus {
            box-shadow: none;
        }
        /* Active page styling */
        div[data-testid="stSidebar"] button[kind="primary"] {
            background-color: rgba(151, 166, 195, 0.25);
            border: none;
            text-align: left;
            padding: 0.5rem 1rem;
            width: 100%;
            font-weight: 600;
        }
        </style>
    """, unsafe_allow_html=True)

    # Initialize page state
    if "current_page" not in st.session_state:
        st.session_state.current_page = "Overview"

    # --- SIDEBAR NAVIGATION ---
    pages = [
        ("📈", "Overview"),
        ("🏦", "Holdings"),
        ("💰", "Dividends"),
        ("💳", "Interest"),
        ("💸", "Fees"),
        ("📝", "Activity"),
        ("💱", "FX Analysis"),
        ("📊", "Performance"),
    ]

    with st.sidebar:
        for icon, name in pages:
            is_active = st.session_state.current_page == name
            if st.button(
                f"{icon} {name}",
                key=f"nav_{name}",
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                st.session_state.current_page = name
                st.rerun()

        st.write("")
        st.write("")
        st.divider()
        st.caption(f"Base: {BASE_CURRENCY}")
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            st.session_state["password_correct"] = False
            st.rerun()

    page = st.session_state.current_page

    # ========================================
    # PAGE: OVERVIEW
    # ========================================
    if page == "Overview":
        st.title("Portfolio Overview")

        @st.cache_data(ttl=CACHE_TTL)
        def load_summary_data():
            with get_db_connection() as conn:
                df_holdings = get_holdings()

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

                total_cash_base = pd.read_sql_query(
                    "SELECT COALESCE(SUM(amount_local), 0) as total FROM transactions",
                    conn
                ).iloc[0]['total']

            price_map = {row['instrument_id']: {'price': row['close'], 'currency': row['currency']}
                        for _, row in prices.iterrows()}
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
                        'Asset Class': meta.get('asset_class') or 'Equity'
                    })

            income = get_income_and_costs()

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
            acol1, acol2 = st.columns(2)
            with acol1:
                fig_sector = px.pie(df_alloc, values='Market Value', names='Sector',
                                    title='By Sector', color_discrete_sequence=PALETTE, hole=0.4)
                apply_plotly_theme(fig_sector)
                st.plotly_chart(fig_sector, use_container_width=True)
            with acol2:
                fig_region = px.pie(df_alloc, values='Market Value', names='Region',
                                    title='By Region', color_discrete_sequence=PALETTE, hole=0.4)
                apply_plotly_theme(fig_region)
                st.plotly_chart(fig_region, use_container_width=True)

    # ========================================
    # PAGE: HOLDINGS
    # ========================================
    elif page == "Holdings":
        st.title("🏦 Holdings")

        @st.cache_data(ttl=CACHE_TTL)
        def load_holdings_data():
            with get_db_connection() as conn:
                df_holdings = get_holdings()

                prices = pd.read_sql_query('''
                    SELECT mp.instrument_id, mp.close, i.currency, i.symbol, i.name,
                           i.sector, i.region, i.country, i.asset_class
                    FROM market_prices mp
                    JOIN instruments i ON mp.instrument_id = i.id
                    WHERE (mp.instrument_id, mp.date) IN (
                        SELECT instrument_id, MAX(date)
                        FROM market_prices
                        GROUP BY instrument_id
                    )
                ''', conn)

            price_map = {row['instrument_id']: row for _, row in prices.iterrows()}
            fx_cache = {}
            data = []
            total_val = 0

            for _, row in df_holdings.iterrows():
                inst_id = row['instrument_id']
                mkt = price_map.get(inst_id)

                if mkt is None:
                    continue

                price = mkt['close']
                curr = mkt['currency']
                market_val = row['quantity'] * convert_to_base(price, curr, fx_cache)
                cost_basis = row['cost_basis_local']
                gain = market_val - cost_basis
                ret_pct = (market_val / cost_basis - 1) * 100 if cost_basis > 0 else 0

                total_val += market_val

                data.append({
                    "Symbol": row['symbol'],
                    "Quantity": int(round(row['quantity'], 0)),
                    "Sector": mkt['sector'],
                    "Region": mkt['region'],
                    "Country": mkt['country'],
                    "Type": mkt['asset_class'],
                    "Market Value": int(round(market_val, 0)),
                    "Gain/Loss": int(round(gain, 0)),
                    "Return %": round(ret_pct, 1)
                })

            df = pd.DataFrame(data)
            if not df.empty:
                df['Weight %'] = round((df['Market Value'] / total_val) * 100, 1)
                df = df.sort_values('Market Value', ascending=False)

            return df

        df = load_holdings_data()

        st.metric("Total Equity Value", format_local(df['Market Value'].sum()) if not df.empty else "0")

        if not df.empty:
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

    # ========================================
    # PAGE: DIVIDENDS
    # ========================================
    elif page == "Dividends":
        st.title("💰 Dividend Analysis")

        @st.cache_data(ttl=CACHE_TTL)
        def load_dividend_data():
            return get_dividend_details()

        @st.cache_data(ttl=CACHE_TTL)
        def load_dividend_forecast():
            return get_dividend_forecast()

        df_yearly, df_current_year, df_all_time = load_dividend_data()

        if not df_current_year.empty:
            df_current_year['total'] = df_current_year['total'].round(0)
        if not df_all_time.empty:
            df_all_time['total'] = df_all_time['total'].round(0)

        col1, col2 = st.columns([2, 1])

        with col1:
            st.subheader("Dividends by Year")
            if not df_yearly.empty:
                fig = px.bar(df_yearly, x='year', y='total', color_discrete_sequence=[COLORS['positive']])
                fig.update_layout(xaxis_title="", yaxis_title=BASE_CURRENCY, showlegend=False)
                apply_plotly_theme(fig)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Top Payers (Current Year)")
            if not df_current_year.empty:
                st.dataframe(
                    df_current_year,
                    column_config={
                        "symbol": st.column_config.TextColumn("Instrument"),
                        "total": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

        st.divider()
        st.subheader("Top Payers (All Time)")
        if not df_all_time.empty:
            st.dataframe(
                df_all_time.head(30),
                column_config={
                    "symbol": st.column_config.TextColumn("Instrument"),
                    "total": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
                },
                use_container_width=True,
                hide_index=True
            )

        st.divider()
        st.subheader("Dividend Forecast")

        with st.spinner("Fetching dividend forecast..."):
            df_forecast, forecast_summary = load_dividend_forecast()

        if not df_forecast.empty:
            df_forecast['quantity'] = df_forecast['quantity'].round(0)
            df_forecast['annual_estimate'] = df_forecast['annual_estimate'].round(0)
            df_forecast['annual_estimate_local'] = df_forecast['annual_estimate_local'].round(0)

            st.metric("Estimated Annual Dividends", f"{forecast_summary['total_estimate_local']:,.0f} {BASE_CURRENCY}")

            st.dataframe(
                df_forecast.sort_values('annual_estimate_local', ascending=False),
                column_config={
                    "symbol": st.column_config.TextColumn("Symbol"),
                    "quantity": st.column_config.NumberColumn("Shares", format="localized"),
                    "dividend_per_share": st.column_config.NumberColumn("Div/Share", format="%.2f"),
                    "currency": st.column_config.TextColumn("Currency"),
                    "annual_estimate": st.column_config.NumberColumn("Annual Est.", format="localized"),
                    "annual_estimate_local": st.column_config.NumberColumn(f"Est. ({BASE_CURRENCY})", format="localized"),
                    "source": st.column_config.TextColumn("Source"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No dividend-paying holdings found.")

    # ========================================
    # PAGE: INTEREST
    # ========================================
    elif page == "Interest":
        st.title("💳 Interest Analysis")

        @st.cache_data(ttl=CACHE_TTL)
        def load_interest_data():
            return get_interest_details()

        df_yearly, df_currency, df_top = load_interest_data()

        if not df_currency.empty:
            df_currency['total'] = df_currency['total'].round(0)
        if not df_top.empty:
            df_top['amount'] = df_top['amount'].round(0)
            df_top['amount_local'] = df_top['amount_local'].round(0)

        total_interest = df_yearly['total'].sum() if not df_yearly.empty else 0
        st.metric("Total Interest Paid (All Time)", format_local(total_interest))

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Interest by Year")
            if not df_yearly.empty:
                fig = px.bar(df_yearly, x='year', y='total', color_discrete_sequence=[COLORS['primary']])
                fig.update_layout(xaxis_title="", yaxis_title=BASE_CURRENCY, showlegend=False)
                apply_plotly_theme(fig)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Interest by Currency")
            if not df_currency.empty:
                st.dataframe(
                    df_currency,
                    column_config={
                        "currency": st.column_config.TextColumn("Currency"),
                        "total": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

        st.subheader("Recent Interest Payments")
        if not df_top.empty:
            st.dataframe(
                df_top,
                column_config={
                    "date": st.column_config.DateColumn("Date"),
                    "currency": st.column_config.TextColumn("Curr"),
                    "amount": st.column_config.NumberColumn("Amount (Orig)", format="localized"),
                    "amount_local": st.column_config.NumberColumn(f"Amount ({BASE_CURRENCY})", format="localized"),
                    "source_file": st.column_config.TextColumn("Source"),
                },
                use_container_width=True,
                hide_index=True
            )

    # ========================================
    # PAGE: FEES
    # ========================================
    elif page == "Fees":
        st.title("💸 Fee Analysis")

        @st.cache_data(ttl=CACHE_TTL)
        def load_fee_data():
            return get_fee_details()

        df_yearly, df_currency, df_top = load_fee_data()

        if not df_currency.empty:
            df_currency['total'] = df_currency['total'].round(0)
        if not df_top.empty:
            df_top['amount_local'] = df_top['amount_local'].round(0)

        total_fees = df_yearly['total'].sum() if not df_yearly.empty else 0
        st.metric("Total Fees Paid (All Time)", format_local(total_fees))

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Fees by Year")
            if not df_yearly.empty:
                fig = px.bar(df_yearly, x='year', y='total', color_discrete_sequence=[COLORS['warning']])
                fig.update_layout(xaxis_title="", yaxis_title=BASE_CURRENCY, showlegend=False)
                apply_plotly_theme(fig)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Fees by Currency")
            if not df_currency.empty:
                st.dataframe(
                    df_currency,
                    column_config={
                        "currency": st.column_config.TextColumn("Currency"),
                        "total": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

        st.divider()
        st.subheader("Recent Individual Fees")
        if not df_top.empty:
            st.dataframe(
                df_top,
                column_config={
                    "date": st.column_config.DateColumn("Date"),
                    "currency": st.column_config.TextColumn("Currency"),
                    "amount_local": st.column_config.NumberColumn(f"Fee ({BASE_CURRENCY})", format="localized"),
                    "source_file": st.column_config.TextColumn("Source"),
                },
                use_container_width=True,
                hide_index=True
            )

        st.divider()
        st.subheader("Fee Efficiency by Broker")
        st.caption(f"Cost per 100 {BASE_CURRENCY} traded (lower is better)")

        df_broker = get_fee_analysis()
        if not df_broker.empty:
            df_broker['total_traded'] = df_broker['total_traded'].round(0)
            df_broker['total_fees'] = df_broker['total_fees'].round(0)
            df_broker['num_trades'] = df_broker['num_trades'].round(0)

            col1, col2 = st.columns([2, 1])

            with col1:
                st.dataframe(
                    df_broker,
                    column_config={
                        "broker": st.column_config.TextColumn("Broker"),
                        "total_traded": st.column_config.NumberColumn(f"Total Traded ({BASE_CURRENCY})", format="localized"),
                        "total_fees": st.column_config.NumberColumn(f"Total Fees ({BASE_CURRENCY})", format="localized"),
                        "fee_per_100": st.column_config.NumberColumn(f"Fee per 100 {BASE_CURRENCY}", format="%.4f"),
                        "num_trades": st.column_config.NumberColumn("# Trades", format="localized"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            with col2:
                fig = px.bar(df_broker, x='broker', y='fee_per_100',
                             color_discrete_sequence=[COLORS['negative']])
                fig.update_layout(xaxis_title="", yaxis_title=f"Fee per 100 {BASE_CURRENCY}", showlegend=False)
                apply_plotly_theme(fig)
                st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Platform & Custody Fees")
        st.caption("Monthly subscription/custody fees (not per-trade)")

        df_platform = get_platform_fees()
        if not df_platform.empty:
            df_platform['total_fees'] = df_platform['total_fees'].round(0)
            df_platform['monthly_avg'] = df_platform['monthly_avg'].round(0)
            df_platform['num_charges'] = df_platform['num_charges'].round(0)

            col1, col2 = st.columns([2, 1])

            with col1:
                st.dataframe(
                    df_platform,
                    column_config={
                        "broker": st.column_config.TextColumn("Broker"),
                        "total_fees": st.column_config.NumberColumn(f"Total ({BASE_CURRENCY})", format="localized"),
                        "monthly_avg": st.column_config.NumberColumn(f"Avg Monthly ({BASE_CURRENCY})", format="localized"),
                        "num_charges": st.column_config.NumberColumn("# Charges", format="localized"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            with col2:
                fig = px.bar(df_platform, x='broker', y='monthly_avg',
                             color_discrete_sequence=[COLORS['purple']])
                fig.update_layout(xaxis_title="", yaxis_title=f"Monthly Avg ({BASE_CURRENCY})", showlegend=False)
                apply_plotly_theme(fig)
                st.plotly_chart(fig, use_container_width=True)

    # ========================================
    # PAGE: ACTIVITY
    # ========================================
    elif page == "Activity":
        st.title("📝 Portfolio Activity")

        col1, col2 = st.columns([2, 1])
        with col1:
            show_all = st.checkbox("Show All Transactions")
            num_txns = st.slider("Number of transactions", 10, 500, 50, disabled=show_all)

        @st.cache_data(ttl=CACHE_TTL)
        def load_activity_data(limit, all_txns):
            with get_db_connection() as conn:
                query = """
                    SELECT
                        t.date,
                        a.name as account,
                        t.type,
                        COALESCE(i.symbol, i.isin) as symbol,
                        t.quantity,
                        t.price,
                        t.amount,
                        t.currency,
                        t.amount_local,
                        t.batch_id,
                        t.source_file,
                        t.notes as description
                    FROM transactions t
                    JOIN accounts a ON t.account_id = a.id
                    LEFT JOIN instruments i ON t.instrument_id = i.id
                    ORDER BY t.date DESC, t.id DESC
                """
                if not all_txns:
                    query += f" LIMIT {limit}"

                df = pd.read_sql_query(query, conn)
            return df

        df = load_activity_data(num_txns, show_all)

        st.metric("Transactions Displayed", len(df))

        df['quantity'] = df['quantity'].round(2)
        df['price'] = df['price'].round(2)
        df['amount'] = df['amount'].round(2)
        df['amount_local'] = df['amount_local'].round(2)

        st.dataframe(
            df,
            column_config={
                "date": st.column_config.DateColumn("Date"),
                "account": st.column_config.TextColumn("Account"),
                "type": st.column_config.TextColumn("Type"),
                "symbol": st.column_config.TextColumn("Instrument"),
                "quantity": st.column_config.NumberColumn("Qty", format="localized"),
                "price": st.column_config.NumberColumn("Price", format="localized"),
                "amount": st.column_config.NumberColumn("Amount", format="localized"),
                "currency": st.column_config.TextColumn("Curr"),
                "amount_local": st.column_config.NumberColumn(f"Amount ({BASE_CURRENCY})", format="localized"),
                "batch_id": st.column_config.TextColumn("Batch"),
                "source_file": st.column_config.TextColumn("Source"),
                "description": st.column_config.TextColumn("Notes"),
            },
            use_container_width=True,
            hide_index=True,
            height=600
        )

    # ========================================
    # PAGE: FX ANALYSIS
    # ========================================
    elif page == "FX Analysis":
        st.title("💱 Currency Performance")

        @st.cache_data(ttl=CACHE_TTL)
        def load_fx_data():
            return get_fx_performance_detailed()

        df = load_fx_data()

        if df.empty:
            st.info("No foreign currency exposure found.")
        else:
            total_realized = df['total_realized_pl'].sum()
            total_unrealized = df['total_unrealized_pl'].sum()

            col1, col2, col3 = st.columns(3)
            col1.metric("Realized FX P&L", format_local(total_realized))
            col2.metric("Unrealized FX P&L", format_local(total_unrealized))
            col3.metric("Total FX P&L", format_local(total_realized + total_unrealized))

            st.divider()
            st.subheader("FX P&L by Currency")

            display_df = df[[
                'currency', 'realized_cash_pl', 'realized_securities_pl',
                'total_realized_pl', 'unrealized_securities_pl', 'total_unrealized_pl'
            ]].copy()
            display_df['total_fx_pl'] = display_df['total_realized_pl'] + display_df['total_unrealized_pl']

            numeric_cols = ['realized_cash_pl', 'realized_securities_pl', 'total_realized_pl',
                           'unrealized_securities_pl', 'total_unrealized_pl', 'total_fx_pl']
            for col in numeric_cols:
                display_df[col] = display_df[col].round(0)

            st.dataframe(
                display_df,
                column_config={
                    "currency": st.column_config.TextColumn("Currency"),
                    "realized_cash_pl": st.column_config.NumberColumn(f"Cash P&L ({BASE_CURRENCY})", format="localized"),
                    "realized_securities_pl": st.column_config.NumberColumn("Securities (Realized)", format="localized"),
                    "total_realized_pl": st.column_config.NumberColumn("Total Realized", format="localized"),
                    "unrealized_securities_pl": st.column_config.NumberColumn("Securities (Unrealized)", format="localized"),
                    "total_unrealized_pl": st.column_config.NumberColumn("Total Unrealized", format="localized"),
                    "total_fx_pl": st.column_config.NumberColumn(f"Total FX P&L ({BASE_CURRENCY})", format="localized"),
                },
                use_container_width=True,
                hide_index=True
            )

    # ========================================
    # PAGE: PERFORMANCE
    # ========================================
    elif page == "Performance":
        st.title("📊 Portfolio Performance")

        @st.cache_data(ttl=CACHE_TTL)
        def load_total_xirr():
            return get_total_xirr()

        @st.cache_data(ttl=CACHE_TTL)
        def load_yearly_equity():
            return get_yearly_equity_curve()

        @st.cache_data(ttl=CACHE_TTL)
        def load_yearly_contrib(year):
            return get_yearly_contribution(year)

        with st.spinner("Calculating performance..."):
            total_xirr = load_total_xirr()

        st.metric("All-Time XIRR (Annualized)", f"{format_local(total_xirr, 2)}%")
        st.divider()

        with st.spinner("Loading yearly data..."):
            df_years, missing_prices = load_yearly_equity()

        if not df_years.empty:
            df_years['start_equity'] = df_years['start_equity'].round(0)
            df_years['net_flow'] = df_years['net_flow'].round(0)
            df_years['end_equity'] = df_years['end_equity'].round(0)
            df_years['profit'] = df_years['profit'].round(0)

            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=df_years['year'],
                y=df_years['end_equity'],
                name='End Equity',
                marker_color=COLORS['primary'],
                yaxis='y'
            ))

            fig.add_trace(go.Scatter(
                x=df_years['year'],
                y=df_years['return_pct'],
                name='Annual Return (%)',
                mode='lines+markers',
                line=dict(color=COLORS['positive'], width=3),
                yaxis='y2'
            ))

            fig.update_layout(
                title='Yearly Equity & Returns',
                xaxis=dict(title=''),
                yaxis=dict(title=f'Equity ({BASE_CURRENCY})', side='left', showgrid=False),
                yaxis2=dict(title='Return (%)', side='right', overlaying='y', showgrid=True),
                legend=dict(x=0.01, y=0.99),
            )
            apply_plotly_theme(fig)
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("Yearly Summary")
            st.dataframe(
                df_years,
                column_config={
                    "year": st.column_config.TextColumn("Year"),
                    "start_equity": st.column_config.NumberColumn("Start Value", format="localized"),
                    "net_flow": st.column_config.NumberColumn("Net Deposits", format="localized"),
                    "end_equity": st.column_config.NumberColumn("End Value", format="localized"),
                    "profit": st.column_config.NumberColumn(f"Profit ({BASE_CURRENCY})", format="localized"),
                    "return_pct": st.column_config.NumberColumn("XIRR %", format="%.2f%%"),
                },
                use_container_width=True,
                hide_index=True
            )

            if missing_prices:
                with st.expander("Missing / Fallback Prices"):
                    st.dataframe(pd.DataFrame(missing_prices))

            st.divider()
            st.subheader("Detailed Analysis by Year")

            selected_year = st.selectbox(
                "Select Year",
                df_years['year'].sort_values(ascending=False).tolist()
            )

            if selected_year:
                with st.spinner(f"Analyzing {selected_year}..."):
                    df_contrib, year_xirr, missing_year = load_yearly_contrib(selected_year)

                st.metric(f"{selected_year} XIRR", f"{year_xirr:.2f}%")

                if not df_contrib.empty:
                    df_contrib['SOY Value'] = df_contrib['SOY Value'].round(0)
                    df_contrib['Net Additions'] = df_contrib['Net Additions'].round(0)
                    df_contrib['EOY Value'] = df_contrib['EOY Value'].round(0)
                    df_contrib['Dividends'] = df_contrib['Dividends'].round(0)
                    df_contrib['Profit'] = df_contrib['Profit'].round(0)

                    df_tree = df_contrib[abs(df_contrib['Contribution %']) > 0.05].copy()

                    fig_tree = px.treemap(
                        df_tree,
                        path=['Symbol'],
                        values=abs(df_tree['Contribution %']),
                        color='Contribution %',
                        color_continuous_scale='RdBu',
                        color_continuous_midpoint=0,
                        title=f"Performance Contribution ({selected_year})"
                    )
                    apply_plotly_theme(fig_tree)
                    st.plotly_chart(fig_tree, use_container_width=True)

                    st.dataframe(
                        df_contrib,
                        column_config={
                            "Symbol": st.column_config.TextColumn("Instrument"),
                            "SOY Value": st.column_config.NumberColumn("SOY Value", format="localized"),
                            "Net Additions": st.column_config.NumberColumn("Net Additions", format="localized"),
                            "EOY Value": st.column_config.NumberColumn("EOY Value", format="localized"),
                            "Dividends": st.column_config.NumberColumn("Divs", format="localized"),
                            "Profit": st.column_config.NumberColumn("Profit", format="localized"),
                            "IRR %": st.column_config.NumberColumn("IRR %", format="%.1f%%"),
                            "Contribution %": st.column_config.NumberColumn("Contr. %", format="%.2f%%"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )

                    st.caption("""
                    **Legend:** [Items in Brackets] = non-instrument totals (Fees, Interest, Tax).
                    [Cash FX & Float] = P&L from uninvested cash or margin debt due to currency movements.
                    """)

                    if missing_year:
                        with st.expander(f"Missing Prices for {selected_year}"):
                            st.dataframe(pd.DataFrame(missing_year))
        else:
            st.info("No yearly data available.")
