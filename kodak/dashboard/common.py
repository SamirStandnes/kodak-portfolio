"""Shared dashboard setup — eliminates boilerplate across pages."""

import sys
from pathlib import Path


def setup_path():
    """Add project root to sys.path. Call at top of every page."""
    # From kodak/dashboard/ → project root is 2 levels up
    # From kodak/dashboard/pages/ → project root is 3 levels up
    import inspect
    caller_file = inspect.stack()[1].filename
    caller_path = Path(caller_file).resolve()

    # Walk up until we find config.yaml (project root)
    for parent in caller_path.parents:
        if (parent / "config.yaml").exists():
            root = str(parent)
            if root not in sys.path:
                sys.path.append(root)
            return root

    # Fallback: assume 3 levels up from caller
    root = str(caller_path.parent.parent.parent)
    if root not in sys.path:
        sys.path.append(root)
    return root


# Run on import so pages just need: from kodak.dashboard.common import *
_project_root = setup_path()


import streamlit as st
import plotly.graph_objects as go
from kodak.shared.utils import load_config, format_local
from kodak.shared.constants import CACHE_TTL, TABLE_HEIGHT, COLORS, PLOTLY_LAYOUT

# Shared config — loaded once
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')


def page_setup(title: str, icon: str):
    """Standard page config + title. Call once per page."""
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
