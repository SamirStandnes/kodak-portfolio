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
    display_table, number_col, text_col, render_chart, load_portfolio_history,
)
from kodak.shared.calculations import (
    get_yearly_equity_curve, get_yearly_contribution, get_total_xirr, get_realized_performance,
)

page_setup("Performance", "📊", "Your money-weighted return (XIRR), time-weighted return against OSEBX, MSCI World and S&P 500, realized results, and what drove each year.")


@st.cache_data(ttl=CACHE_TTL)
def load_total_xirr():
    return get_total_xirr()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_equity_curve():
    return get_yearly_equity_curve()


@st.cache_data(ttl=CACHE_TTL)
def load_yearly_contribution(year: str):
    return get_yearly_contribution(year)


@st.cache_data(ttl=CACHE_TTL)
def load_realized_performance():
    return get_realized_performance()


# --- 1. All-Time ---
with st.spinner("Calculating All-Time Performance..."):
    total_xirr = load_total_xirr()

with st.spinner("Fetching Yearly Data..."):
    df_years, missing_prices = load_yearly_equity_curve()

df_realized = load_realized_performance()

k1, k2, k3 = st.columns(3)
k1.metric("All-Time XIRR (Annualized)", format_pct(total_xirr, 2),
          help="Money-weighted return on all deposits and withdrawals, valued at live prices.")
if not df_years.empty:
    total_profit = df_years['profit'].sum()
    k2.metric("Cumulative Profit", format_local(total_profit),
              help="Current value minus all net deposits, i.e. everything the portfolio has earned "
                   "(price gains, dividends, interest, fees, tax). Valued at live Yahoo prices; the "
                   "Overview's 'Total Gain vs Deposits' uses the last stored prices, so the two differ "
                   "by the market move since the last price refresh.")
    best = df_years.loc[df_years['return_pct'].idxmax()]
    k3.metric("Best Year", f"{best['year']}: {format_pct(best['return_pct'], 1, sign=True)}")
st.divider()

# --- 2. Yearly Timeline ---
if not df_years.empty:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_years['year'], y=df_years['end_equity'],
        name=f'End equity ({BASE_CURRENCY})', yaxis='y', width=0.42,
        marker=dict(color='rgba(102,126,234,0.55)', line=dict(color=COLORS['primary'], width=1.5),
                    cornerradius=6),
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>End equity</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_years['year'], y=df_years['return_pct'],
        name='Annual return (XIRR)', mode='lines+markers+text', yaxis='y2',
        line=dict(color=COLORS['positive'], width=2.5, shape='spline', smoothing=0.6),
        marker=dict(size=9, color=COLORS['positive'], line=dict(color=COLORS['bg'], width=2)),
        text=[f"{v:+.0f} %" for v in df_years['return_pct']], textposition='top center',
        textfont=dict(size=11, color=COLORS['text'], family="'JetBrains Mono', monospace"),
        hovertemplate="%{y:+.2f} %<extra>XIRR</extra>",
    ))
    pad = max(abs(df_years['return_pct'].min()), abs(df_years['return_pct'].max())) * 1.35
    fig.update_layout(
        yaxis=dict(side='left', showgrid=True, title=f'Equity ({BASE_CURRENCY})', rangemode='tozero'),
        yaxis2=dict(side='right', overlaying='y', showgrid=False, title='Return (%)',
                    range=[-pad, pad], zeroline=True, zerolinecolor='rgba(139,148,158,0.5)',
                    zerolinewidth=1, ticksuffix=' %',
                    tickfont=dict(color=COLORS['text_secondary'], size=11, family="'JetBrains Mono', monospace"),
                    title_font=dict(color=COLORS['text_secondary'], size=11)),
        legend=dict(orientation='h', y=1.1, x=0),
        xaxis_title='', xaxis=dict(type='category'), hovermode='x unified',
        bargap=0.5, margin=dict(l=48, r=48, t=48, b=40), height=420,
    )
    st.subheader("Yearly Equity & Returns")
    render_chart(fig)

    st.subheader("Yearly Summary")
    display_table(df_years, {
        "year": text_col("Year"),
        "start_equity": number_col("Start Value"),
        "net_flow": number_col("Net Deposits"),
        "end_equity": number_col("End Value"),
        "profit": number_col(f"Profit ({BASE_CURRENCY})"),
        "return_pct": number_col("XIRR %", fmt="%.2f%%"),
    }, height=min(400, 40 * len(df_years) + 60))

    if missing_prices:
        with st.expander("Missing / Fallback Prices Used"):
            st.dataframe(pd.DataFrame(missing_prices), width="stretch", hide_index=True)
else:
    st.info("No yearly data available.")

st.divider()

# --- 2b. Versus benchmarks (time-weighted) ---
st.subheader("Versus Benchmarks")
st.caption(
    "Time-weighted: the growth of 1 krone kept invested, so the timing and size of your deposits "
    f"do not matter. That is how an index is measured, so this is the like-for-like comparison. "
    f"All series in {BASE_CURRENCY}; indices are total return (dividends reinvested)."
)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Comparing with benchmarks...")
def load_benchmark_comparison(xirr_pct: float):
    from kodak.shared.benchmarks import compare_to_benchmarks
    return compare_to_benchmarks(load_portfolio_history(), portfolio_xirr_pct=xirr_pct)


cmp = load_benchmark_comparison(total_xirr)
if cmp is None or cmp.growth.shape[1] < 2:
    st.info("No benchmark prices stored yet. Run `python -m kodak.pipeline.fetch_benchmarks` "
            "(part of refresh_market_data.ps1).")
else:
    names = [c for c in cmp.growth.columns if c != 'Portfolio']
    bcols = st.columns(1 + len(names))
    bcols[0].metric("Portfolio (annualized TWR)", format_pct(cmp.annualized['Portfolio'], 2),
                    help=f"Since {cmp.start:%d %b %Y}")
    for col, name in zip(bcols[1:], names):
        diff = cmp.annualized['Portfolio'] - cmp.annualized[name]
        col.metric(name, format_pct(cmp.annualized[name], 2), format_pct(diff, 2, sign=True),
                   help=f"Delta = portfolio minus {name}, annualized")

    fig_b = go.Figure()
    fig_b.add_trace(go.Scatter(
        x=cmp.growth.index, y=cmp.growth['Portfolio'], name='Portfolio', mode='lines',
        line=dict(color=COLORS['primary'], width=2.5),
        hovertemplate="%{y:,.1f}<extra>Portfolio</extra>",
    ))
    for name, color in zip(names, [COLORS['positive'], COLORS['warning'], COLORS['pink'], COLORS['light_blue']]):
        fig_b.add_trace(go.Scatter(
            x=cmp.growth.index, y=cmp.growth[name], name=name, mode='lines',
            line=dict(color=color, width=1.6),
            hovertemplate=f"%{{y:,.1f}}<extra>{name}</extra>",
        ))
    fig_b.update_layout(
        yaxis=dict(title='Growth of 100'), xaxis=dict(
            rangeselector=dict(buttons=[
                dict(count=1, label="1Y", step="year", stepmode="backward"),
                dict(count=3, label="3Y", step="year", stepmode="backward"),
                dict(label="YTD", step="year", stepmode="todate"),
                dict(label="All", step="all"),
            ], bgcolor=COLORS['bg_surface'], activecolor=COLORS['primary'], font=dict(color=COLORS['text'])),
        ),
        legend=dict(orientation='h', y=-0.18, x=0), hovermode='x unified',
        margin=dict(l=48, r=24, t=40, b=70), height=440,
    )
    render_chart(fig_b)

    yt = cmp.yearly.rename_axis('Year').reset_index()
    if not df_years.empty:
        yt = yt.merge(df_years[['year', 'return_pct']].rename(columns={'year': 'Year', 'return_pct': 'Portfolio XIRR'}),
                      on='Year', how='left')
        yt = yt[['Year', 'Portfolio XIRR', 'Portfolio TWR'] + names]
    ycfg = {"Year": text_col("Year")}
    for c in yt.columns[1:]:
        ycfg[c] = number_col(c, fmt="%.1f%%")
    st.markdown("**By year** (percent). XIRR is your money-weighted return; TWR and the indices are time-weighted.")
    display_table(yt, ycfg, height=min(400, 34 * len(yt) + 44))

    if not cmp.shadow.empty:
        st.markdown(f"**Same deposits in the index.** Every deposit and withdrawal you made, placed in the "
                    f"index on the same day. Value today and money-weighted return, directly comparable with yours.")
        sh = cmp.shadow.copy()
        sh['portfolio_xirr_pct'] = sh['portfolio_xirr_pct'].fillna(total_xirr)
        display_table(sh, {
            "benchmark": text_col("Benchmark"),
            "index_value": number_col(f"Index value today ({BASE_CURRENCY})"),
            "portfolio_value": number_col(f"Your value ({BASE_CURRENCY})"),
            "difference": number_col(f"You vs index ({BASE_CURRENCY})"),
            "index_xirr_pct": number_col("Index XIRR", fmt="%.2f%%"),
            "portfolio_xirr_pct": number_col("Your XIRR", fmt="%.2f%%"),
        }, height=34 * len(sh) + 44)
    if cmp.missing:
        st.caption("No stored prices yet for: " + ", ".join(cmp.missing))

st.divider()

# --- 3. Realized P&L by Year ---
st.subheader("Realized P&L by Year")
st.caption("What actually hit the account each year: gains on sales, dividends, interest, fees and withholding tax. "
           "Unrealized gains on open positions are not included.")
if df_realized.empty:
    st.info("No realized data available.")
else:
    components = [
        ('realized_gl', 'Realized Gains', COLORS['primary']),
        ('dividends', 'Dividends', COLORS['positive']),
        ('interest', 'Interest', COLORS['warning']),
        ('fees', 'Fees', COLORS['negative']),
        ('tax', 'Tax', COLORS['purple']),
    ]
    fig_r = go.Figure()
    for col, label, color in components:
        fig_r.add_trace(go.Bar(
            x=df_realized['year'], y=df_realized[col], name=label, marker_color=color,
            hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>{label}</extra>",
        ))
    fig_r.add_trace(go.Scatter(
        x=df_realized['year'], y=df_realized['total_pl'], name='Net', mode='lines+markers',
        line=dict(color=COLORS['text'], width=2), marker=dict(size=8),
        hovertemplate=f"%{{y:,.0f}} {BASE_CURRENCY}<extra>Net</extra>",
    ))
    fig_r.update_layout(
        barmode='relative', xaxis=dict(type='category', title=''),
        yaxis_title=BASE_CURRENCY, legend=dict(orientation='h', y=1.08, x=0),
    )
    render_chart(fig_r)

    display_table(df_realized[['year', 'realized_gl', 'dividends', 'interest', 'fees', 'tax', 'total_pl']], {
        "year": text_col("Year"),
        "realized_gl": number_col("Realized Gains"),
        "dividends": number_col("Dividends"),
        "interest": number_col("Interest"),
        "fees": number_col("Fees"),
        "tax": number_col("Tax"),
        "total_pl": number_col(f"Net ({BASE_CURRENCY})"),
    }, height=min(400, 40 * len(df_realized) + 60))

st.divider()

# --- 4. Detailed Year View ---
st.subheader("Detailed Analysis by Year")
selected_year = st.selectbox(
    "Select Year",
    df_years['year'].sort_values(ascending=False).tolist() if not df_years.empty else [],
)

if selected_year:
    with st.spinner(f"Analyzing {selected_year}..."):
        df_contrib, year_xirr, missing_prices_year = load_yearly_contribution(selected_year)

    st.metric(f"{selected_year} XIRR", format_pct(year_xirr, 2))

    if not df_contrib.empty:
        df_tree = df_contrib[abs(df_contrib['Contribution %']) > 0.05].copy()

        if not df_tree.empty:
            st.markdown(f"**Performance contribution, {selected_year}** — box size is the share of the "
                        "year's return each holding explains; colour is its sign.")
            fig_tree = px.treemap(
                df_tree, path=['Symbol'],
                values=abs(df_tree['Contribution %']),
                color='Contribution %',
                color_continuous_scale=[COLORS['negative'], COLORS['bg_surface'], COLORS['positive']],
                color_continuous_midpoint=0,
            )
            fig_tree.update_traces(
                marker=dict(line=dict(color=COLORS['bg'], width=2)),
                textfont=dict(family="'Inter', sans-serif", size=14),
                hovertemplate="<b>%{label}</b><br>Contribution: %{color:+.2f} pp<extra></extra>")
            fig_tree.update_layout(hovermode='closest', margin=dict(l=10, r=10, t=10, b=10),
                                   coloraxis_colorbar=dict(title='pp'))
            render_chart(fig_tree)

        display_table(df_contrib, {
            "Symbol": text_col("Instrument"),
            "SOY Value": number_col("SOY Value"),
            "Net Additions": number_col("Net Additions"),
            "EOY Value": number_col("EOY Value"),
            "Dividends": number_col("Divs"),
            "Profit": number_col("Profit"),
            "IRR %": number_col("IRR %", fmt="%.1f%%"),
            "Contribution %": number_col("Contr. %", fmt="%.2f%%"),
        })

        st.caption("""
        **Legend:** [Items in Brackets] = non-instrument totals (Fees, Interest, Tax).
        [Cash FX & Float] = P&L from uninvested cash or margin debt due to currency movements.
        """)

        if missing_prices_year:
            with st.expander(f"Missing / Fallback Prices for {selected_year}"):
                st.info("Detailed analysis requires pricing for both Start of Year and End of Year. The Timeline view only checks End of Year.")
                st.dataframe(pd.DataFrame(missing_prices_year), width="stretch", hide_index=True)
