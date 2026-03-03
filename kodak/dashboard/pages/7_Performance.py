import sys
from pathlib import Path
# Add project root to sys.path
root_path = str(Path(__file__).resolve().parent.parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from kodak.shared.calculations import get_yearly_equity_curve, get_yearly_contribution, get_total_xirr
from kodak.shared.utils import load_config, format_local
from kodak.dashboard.style import apply_theme, page_header, styled_subheader, get_plotly_layout, COLORS, CHART_COLORS

# --- CONFIGURATION ---
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')

st.set_page_config(page_title="Performance", page_icon="📈", layout="wide")
apply_theme()

page_header("Portfolio Performance", "Returns, XIRR, and contribution analysis")

# --- CACHED DATA LOADERS ---
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_total_xirr():
    return get_total_xirr()

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_yearly_equity_curve():
    return get_yearly_equity_curve()

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_yearly_contribution(year: str):
    return get_yearly_contribution(year)

# --- 1. All-Time Stats ---
with st.spinner("Calculating All-Time Performance..."):
    total_xirr = load_total_xirr()

st.metric("All-Time XIRR (Annualized)", f"{format_local(total_xirr, 2)}%")
st.divider()

# --- 2. Yearly Timeline ---
with st.spinner("Fetching Yearly Data..."):
    df_years, missing_prices = load_yearly_equity_curve()

if not df_years.empty:
    fig = go.Figure()

    # Bar: End Equity
    fig.add_trace(go.Bar(
        x=df_years['year'],
        y=df_years['end_equity'],
        name='End Equity',
        marker_color=COLORS["primary"],
        marker_line_color="#0E1117",
        marker_line_width=1,
        opacity=0.85,
        yaxis='y'
    ))

    # Line: XIRR
    fig.add_trace(go.Scatter(
        x=df_years['year'],
        y=df_years['return_pct'],
        name='Annual Return (%)',
        mode='lines+markers',
        line=dict(color=COLORS["green"], width=3),
        marker=dict(size=8, color=COLORS["green"], line=dict(width=2, color="#0E1117")),
        yaxis='y2'
    ))

    base_layout = get_plotly_layout()
    fig.update_layout(
        **base_layout,
        title='Yearly Equity & Returns',
        xaxis=dict(title='', gridcolor="#21262D", linecolor="#30363D",
                   zerolinecolor="#30363D", title_font=dict(color="#8B949E"),
                   tickfont=dict(color="#8B949E")),
        yaxis=dict(title='Equity', side='left', showgrid=False,
                   gridcolor="#21262D", linecolor="#30363D", zerolinecolor="#30363D",
                   title_font=dict(color="#8B949E"), tickfont=dict(color="#8B949E")),
        yaxis2=dict(title='Return (%)', side='right', overlaying='y', showgrid=True,
                    gridcolor="#21262D", linecolor="#30363D", zerolinecolor="#30363D",
                    title_font=dict(color="#8B949E"), tickfont=dict(color="#8B949E")),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(0,0,0,0)", font=dict(color="#8B949E")),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Table
    styled_subheader("Yearly Summary")
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
        with st.expander("Missing / Fallback Prices Used"):
            st.dataframe(pd.DataFrame(missing_prices))

else:
    st.info("No yearly data available.")

st.divider()

# --- 3. Detailed Year View ---
styled_subheader("Detailed Analysis by Year")
selected_year = st.selectbox("Select Year", df_years['year'].sort_values(ascending=False) if not df_years.empty else [])

if selected_year:
    with st.spinner(f"Analyzing {selected_year}..."):
        df_contrib, year_xirr, missing_prices_year = load_yearly_contribution(selected_year)

    col1, col2 = st.columns(2)
    col1.metric(f"{selected_year} XIRR", f"{year_xirr:.2f}%")

    # Treemap of Contribution
    if not df_contrib.empty:
        # Filter out tiny contributions for cleaner chart
        df_tree = df_contrib[abs(df_contrib['Contribution %']) > 0.05].copy()
        df_tree['Positive'] = df_tree['Contribution %'] > 0

        fig_tree = px.treemap(
            df_tree,
            path=['Symbol'],
            values=abs(df_tree['Contribution %']),  # Size by magnitude
            color='Contribution %',
            color_continuous_scale='RdBu',
            color_continuous_midpoint=0,
            title=f"Performance Contribution Breakdown ({selected_year})"
        )
        fig_tree.update_layout(**get_plotly_layout())
        fig_tree.update_layout(
            coloraxis_colorbar=dict(
                title="Contr. %",
                tickfont=dict(color="#8B949E"),
                title_font=dict(color="#8B949E"),
            ),
        )
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
        **Legend & Logic:**
        - **[Items in Brackets]**: These are non-instrument totals (Fees, Interest, Tax).
        - **[Cash FX & Float]***: Represents the P&L from your uninvested cash or margin debt.
            - *Positive:* Gain from currency strengthening while holding foreign cash (or weakening while holding debt).
            - *Negative:* Loss from currency movement or unexplained cash drift.
        """)

        if missing_prices_year:
            with st.expander(f"Missing / Fallback Prices for {selected_year}"):
                 st.info("**Why is this list longer?**\n\nDetailed analysis requires pricing for both the **Start of Year** (to calculate opening value) and **End of Year**. The Timeline view only checks the End of Year value.")
                 st.dataframe(pd.DataFrame(missing_prices_year))
