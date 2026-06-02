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


def check_auth():
    """Password gate for Heroku. No-op locally (no DASHBOARD_PASSWORD set).

    Called once from the entry-point router (Home.py) BEFORE st.navigation
    is built, so the sidebar nav literally doesn't exist for unauthenticated
    visitors — no flash, no CSS race.
    """
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        return  # Local mode — no auth

    if st.session_state.get("password_correct"):
        return  # Already authenticated

    st.set_page_config(
        page_title="Kodak Portfolio", page_icon="📈",
        layout="centered", initial_sidebar_state="collapsed",
    )
    st.markdown("""
        <style>
        #MainMenu, header, footer {visibility: hidden !important;}
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
    """Per-page setup: render the page header.

    The theme CSS and sidebar branding are injected once by the entry-point
    router (Home.py) so they're in place before any page body renders.
    """
    from kodak.dashboard.style import page_header
    page_header(f"{icon} {title}")


def _translate_column_config(column_config: dict) -> dict:
    """Convert Streamlit column_config dicts → display_aggrid spec dicts.

    Streamlit column_config objects are plain dicts with `type_config.type` and
    `type_config.format`. We map common patterns; unrecognized columns fall
    through with no special spec (rendered as text).
    """
    import re
    spec = {}
    for col, cfg in (column_config or {}).items():
        if not isinstance(cfg, dict):
            continue
        tc = cfg.get("type_config", {}) or {}
        ctype = tc.get("type")
        fmt = tc.get("format")
        out = {}

        if ctype == "number":
            decimals = 0
            if isinstance(fmt, str):
                if fmt.endswith("%%") or fmt.endswith("%"):
                    out["type"] = "percent"
                    m = re.search(r"%\.(\d+)f", fmt)
                    decimals = int(m.group(1)) if m else 1
                elif fmt == "%d":
                    out["type"] = "number"
                    decimals = 0
                elif re.search(r"%\.(\d+)f", fmt):
                    out["type"] = "number"
                    decimals = int(re.search(r"%\.(\d+)f", fmt).group(1))
                else:
                    out["type"] = "number"
            else:
                out["type"] = "number"
            out["decimals"] = decimals
        elif ctype == "progress":
            out["type"] = "progress"
            out["max"] = tc.get("max_value", 100) or 100
        # text and date fall through with no spec (rendered as plain text)

        if out:
            spec[col] = out
    return spec


def display_table(df, column_config: dict, height: int = TABLE_HEIGHT):
    """Render df via AG-Grid by translating Streamlit column_config to AG-Grid specs."""
    return display_aggrid(df, columns=_translate_column_config(column_config), height=height)


def display_table_native(df, column_config: dict, height: int = TABLE_HEIGHT):
    """Escape hatch — use Streamlit's native dataframe (kept for edge cases)."""
    st.dataframe(
        df,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        height=height,
    )


def _kodak_aggrid_theme():
    """Build the Kodak dark theme using streamlit-aggrid v1.2+ Theming API."""
    from st_aggrid import StAggridTheme
    return (
        StAggridTheme(base="balham")
        .withParams(
            backgroundColor="#0B0E13",
            foregroundColor="#E6EDF3",
            chromeBackgroundColor="#1C2333",
            headerBackgroundColor="#1C2333",
            headerTextColor="#8B949E",
            borderColor="#21262D",
            oddRowBackgroundColor="#0E131A",
            rowHoverColor="#1C2333",
            selectedRowBackgroundColor="#1C2333",
            accentColor="#667EEA",
            fontFamily="Inter, -apple-system, sans-serif",
            fontSize=13,
            rowHeight=38,
            headerHeight=38,
            wrapperBorderRadius=10,
        )
    )


def display_aggrid(df, columns: dict | None = None, height: int = TABLE_HEIGHT, pin_left: list[str] | None = None):
    """Render a DataFrame as an AG-Grid table with the dark Kodak theme.

    `columns` maps column-name → spec dict:
        {"type": "currency"|"percent"|"number"|"text"|"progress",
         "decimals": int,
         "color_signed": bool (green if >0, red if <0),
         "max": float (only for type="progress"),
         "width": int}
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

    columns = columns or {}
    pin_left = pin_left or []
    gb = GridOptionsBuilder.from_dataframe(df)

    gb.configure_default_column(
        resizable=True, sortable=True, filter=True, floatingFilter=False,
    )

    def num_formatter(decimals: int) -> JsCode:
        return JsCode(
            "function(params){"
            "  if (params.value === null || params.value === undefined || isNaN(params.value)) return '';"
            f"  return Number(params.value).toLocaleString('nb-NO', {{minimumFractionDigits:{decimals}, maximumFractionDigits:{decimals}}});"
            "}"
        )

    def pct_formatter(decimals: int) -> JsCode:
        return JsCode(
            "function(params){"
            "  if (params.value === null || params.value === undefined || isNaN(params.value)) return '';"
            f"  return Number(params.value).toFixed({decimals}) + '%';"
            "}"
        )

    def progress_value_formatter(decimals: int = 1) -> JsCode:
        return JsCode(
            "function(params){"
            "  if (params.value === null || params.value === undefined || isNaN(params.value)) return '';"
            f"  return Number(params.value).toFixed({decimals}) + '%';"
            "}"
        )

    def progress_cell_style(max_val: float) -> JsCode:
        return JsCode(
            "function(params){"
            "  const v = Number(params.value) || 0;"
            f"  const max = {max_val};"
            "  const pct = Math.max(0, Math.min(100, (v / max) * 100));"
            "  return {"
            "    background: 'linear-gradient(to right, rgba(102,126,234,0.45) 0%, rgba(118,75,162,0.45) ' + pct + '%, transparent ' + pct + '%)',"
            "    color: '#E6EDF3',"
            "    fontFamily: 'JetBrains Mono, monospace',"
            "    fontSize: '13px',"
            "    paddingLeft: '8px',"
            "    display: 'flex',"
            "    alignItems: 'center',"
            "  };"
            "}"
        )

    signed_color = JsCode(
        "function(params){"
        "  const v = Number(params.value);"
        "  if (isNaN(v)) return {fontFamily:'JetBrains Mono, monospace'};"
        "  if (v > 0) return {color:'#3FB950', fontFamily:'JetBrains Mono, monospace', fontWeight:'600'};"
        "  if (v < 0) return {color:'#F85149', fontFamily:'JetBrains Mono, monospace', fontWeight:'600'};"
        "  return {color:'#8B949E', fontFamily:'JetBrains Mono, monospace'};"
        "}"
    )
    mono_style = {"fontFamily": "JetBrains Mono, monospace"}

    for col, spec in columns.items():
        if col not in df.columns:
            continue
        kwargs = {}
        if "width" in spec:
            kwargs["width"] = spec["width"]
        if col in pin_left:
            kwargs["pinned"] = "left"

        ctype = spec.get("type", "text")
        decimals = spec.get("decimals", 0)
        color_signed = spec.get("color_signed", False)

        if ctype in ("currency", "number"):
            kwargs["valueFormatter"] = num_formatter(decimals)
            kwargs["type"] = "rightAligned"
            kwargs["cellStyle"] = signed_color if color_signed else mono_style
        elif ctype == "percent":
            kwargs["valueFormatter"] = pct_formatter(decimals)
            kwargs["type"] = "rightAligned"
            kwargs["cellStyle"] = signed_color if color_signed else mono_style
        elif ctype == "progress":
            max_val = spec.get("max", 100)
            kwargs["valueFormatter"] = progress_value_formatter(decimals if decimals else 1)
            kwargs["cellStyle"] = progress_cell_style(max_val)
        else:
            if color_signed:
                kwargs["cellStyle"] = signed_color

        gb.configure_column(col, **kwargs)

    for col in pin_left:
        if col in df.columns and col not in columns:
            gb.configure_column(col, pinned="left")

    grid_options = gb.build()

    # AG-Grid renders inside an iframe, so the global ::-webkit-scrollbar CSS in
    # style.py doesn't reach it. Inject matching dark-theme scrollbar rules here.
    aggrid_scrollbar_css = {
        "::-webkit-scrollbar": {"width": "8px !important", "height": "8px !important"},
        "::-webkit-scrollbar-track": {"background": "#0B0E13 !important"},
        "::-webkit-scrollbar-thumb": {"background": "#30363D !important", "border-radius": "4px !important"},
        "::-webkit-scrollbar-thumb:hover": {"background": "#484F58 !important"},
        ".ag-body-horizontal-scroll-viewport, .ag-body-vertical-scroll-viewport": {
            "scrollbar-width": "thin", "scrollbar-color": "#30363D #0B0E13",
        },
    }

    return AgGrid(
        df,
        gridOptions=grid_options,
        theme=_kodak_aggrid_theme(),
        height=height,
        allow_unsafe_jscode=True,
        update_mode="NO_UPDATE",
        custom_css=aggrid_scrollbar_css,
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
    # Defensive: if no chart title has been set, force title.text to an empty
    # string. Plotly.js renders the literal placeholder "undefined" when
    # title.text is missing on the JS side, and Streamlit's plotly theme can
    # wrap that in <b><b>…</b></b>. An explicit "" suppresses both.
    if fig.layout.title.text is None:
        fig.update_layout(title_text="")
    return fig


def convert_to_base(amount: float, currency: str, fx_cache: dict) -> float:
    """Convert an amount to base currency using a shared FX cache."""
    if currency == BASE_CURRENCY:
        return amount
    if currency not in fx_cache:
        from kodak.shared.market_data import get_exchange_rate
        fx_cache[currency] = get_exchange_rate(currency, BASE_CURRENCY)
    return amount * fx_cache[currency]
