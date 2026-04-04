"""Shared dashboard setup — eliminates boilerplate across pages."""

import sys
import os
from pathlib import Path


def setup_path():
    """Add project root to sys.path. Call at top of every page."""
    import inspect
    caller_file = inspect.stack()[1].filename
    caller_path = Path(caller_file).resolve()

    for parent in caller_path.parents:
        if (parent / "config.yaml").exists():
            root = str(parent)
            if root not in sys.path:
                sys.path.append(root)
            return root

    root = str(caller_path.parent.parent.parent)
    if root not in sys.path:
        sys.path.append(root)
    return root


# Run on import so pages just need: from kodak.dashboard.common import *
_project_root = setup_path()

# Auto-detect Heroku: load PostgreSQL adapters before any kodak imports
_IS_HEROKU = bool(os.environ.get("DATABASE_URL"))
if _IS_HEROKU:
    import heroku.setup_adapters  # noqa: F401

import streamlit as st
import plotly.graph_objects as go
from kodak.shared.utils import load_config, format_local
from kodak.shared.constants import CACHE_TTL, TABLE_HEIGHT, COLORS, PLOTLY_LAYOUT

# Shared config — loaded once
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')


def _check_auth():
    """Password gate for Heroku. No-op locally (no DASHBOARD_PASSWORD set)."""
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        return  # Local mode — no auth

    if st.session_state.get("password_correct"):
        return  # Already authenticated

    st.set_page_config(page_title="Kodak Portfolio", page_icon="📈", layout="centered")
    st.markdown("""
        <style>
        #MainMenu, header, footer {visibility: hidden;}
        .block-container { max-width: 420px; padding-top: 8vh; }
        [data-testid="InputInstructions"] { display: none !important; }
        .stForm [data-testid="stFormSubmitButton"] button { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

    st.title("Kodak Portfolio")
    st.caption("Enter your password to continue")

    with st.form("login_form"):
        pwd = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        submitted = st.form_submit_button("Log in", use_container_width=True, type="primary")

    if submitted:
        if pwd == password:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    st.stop()


def page_setup(title: str, icon: str):
    """Standard page config + title. Call once per page."""
    _check_auth()
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    st.title(f"{icon} {title}")


def display_table(df, column_config: dict, height: int = TABLE_HEIGHT):
    """Standard dataframe display with consistent settings."""
    st.dataframe(
        df,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        height=height,
    )


def number_col(label: str, fmt: str = "localized", **kwargs) -> st.column_config.NumberColumn:
    """Shorthand for NumberColumn with localized formatting."""
    return st.column_config.NumberColumn(label, format=fmt, **kwargs)


def text_col(label: str) -> st.column_config.TextColumn:
    """Shorthand for TextColumn."""
    return st.column_config.TextColumn(label)


def date_col(label: str = "Date", fmt: str = "YYYY-MM-DD") -> st.column_config.DateColumn:
    """Shorthand for DateColumn."""
    return st.column_config.DateColumn(label, format=fmt)


def apply_plotly_theme(fig: go.Figure) -> go.Figure:
    """Apply consistent Plotly styling to a figure."""
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig


def convert_to_base(amount: float, currency: str, fx_cache: dict) -> float:
    """Convert an amount to base currency using a shared FX cache."""
    if currency == BASE_CURRENCY:
        return amount
    if currency not in fx_cache:
        from kodak.shared.market_data import get_exchange_rate
        fx_cache[currency] = get_exchange_rate(currency, BASE_CURRENCY)
    return amount * fx_cache[currency]
