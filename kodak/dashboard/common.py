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

# Streamlit Community Cloud provides config via st.secrets, NOT as environment
# variables. The adapter detection below (and config_adapter / db_adapter) keys
# off os.environ, so bridge the relevant top-level secrets into the environment
# first. No-op locally / on Heroku, where these come from .env or real env vars.
try:
    import streamlit as _st
    for _key in ("DATABASE_URL", "DASHBOARD_PASSWORD", "BASE_CURRENCY"):
        if not os.environ.get(_key):
            try:
                _val = _st.secrets[_key]
            except Exception:
                _val = None
            if _val is not None:
                os.environ[_key] = str(_val)
except Exception:
    pass

# Auto-detect Heroku: load PostgreSQL adapters before any kodak imports
_IS_HEROKU = bool(os.environ.get("DATABASE_URL"))
if _IS_HEROKU:
    import heroku.setup_adapters  # noqa: F401

import hmac
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from kodak.shared.utils import load_config, format_local
from kodak.shared.constants import CACHE_TTL, TABLE_HEIGHT, COLORS, PLOTLY_LAYOUT

# Shared config — loaded once
config = load_config()
BASE_CURRENCY = config.get('base_currency', 'NOK')


def format_pct(val, decimals: int = 1, sign: bool = False) -> str:
    """Percent in the same Norwegian style as format_local (e.g. '12,3 %')."""
    if val is None or pd.isna(val):
        return "–"
    prefix = "+" if sign and val > 0 else ""
    return f"{prefix}{format_local(val, decimals)} %"


# ---------------------------------------------------------------------------
# Cached data loaders shared by several pages. Keeping them here (rather than
# one copy per page) means Overview / Holdings / Risk all read the *same*
# cached frame and can never disagree on totals or position counts.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=CACHE_TTL, show_spinner="Valuing holdings...")
def load_valued_holdings() -> pd.DataFrame:
    from kodak.shared.calculations import get_valued_holdings
    return get_valued_holdings()


@st.cache_data(ttl=CACHE_TTL, show_spinner="Building portfolio history...")
def load_portfolio_history() -> pd.DataFrame:
    from kodak.shared.calculations import get_portfolio_value_history
    return get_portfolio_value_history()


def price_freshness(df_valued: pd.DataFrame) -> tuple[str | None, str | None]:
    """(latest price date, previous price date) across the valued holdings."""
    if df_valued.empty or df_valued['price_date'].dropna().empty:
        return None, None
    latest = df_valued['price_date'].dropna().max()
    prev = df_valued['prev_date'].dropna()
    return str(latest), (str(prev.max()) if not prev.empty else None)


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
        /* Streamlit frontend race: "Missing Submit Button" flashes on load/reconnect
           even though the submit button exists (rendered before formsData syncs).
           The form is the only alert-bearing element inside stForm, so this is safe. */
        [data-testid="stForm"] [data-testid="stAlert"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    st.title("Kodak Portfolio")
    st.caption("Enter your password to continue")

    with st.form("login_form"):
        pwd = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        submitted = st.form_submit_button("Log in", width="stretch", type="primary")

    if submitted:
        if hmac.compare_digest(pwd or "", password):
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    st.stop()


def page_setup(title: str, icon: str, description: str = ""):
    """Per-page setup: apply theme + render header. Auth and set_page_config
    are handled by the entry-point router (Home.py)."""
    from kodak.dashboard.style import apply_theme, page_header
    apply_theme()
    page_header(title, icon=icon, description=description)


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
        if cfg.get("label"):
            out["label"] = cfg["label"]
        if cfg.get("help"):
            out["help"] = cfg["help"]

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
        elif ctype == "date":
            out["width"] = 110
        # text falls through with only its label

        if out:
            spec[col] = out
    return spec


def display_table(df, column_config: dict, height: int = TABLE_HEIGHT, totals: dict | None = None,
                  pin_left: list[str] | None = None):
    """Render df via AG-Grid by translating Streamlit column_config to AG-Grid specs."""
    return display_aggrid(df, columns=_translate_column_config(column_config), height=height,
                          totals=totals, pin_left=pin_left)


def display_table_native(df, column_config: dict, height: int = TABLE_HEIGHT):
    """Escape hatch — use Streamlit's native dataframe (kept for edge cases)."""
    st.dataframe(
        df,
        column_config=column_config,
        width="stretch",
        hide_index=True,
        height=height,
    )


def _kodak_aggrid_theme():
    """Kodak dark theme via the streamlit-aggrid v1.2+ (AG Grid v33) Theming API."""
    from st_aggrid import StAggridTheme
    return (
        StAggridTheme(base="balham")
        .withParams(
            backgroundColor=COLORS["bg"],
            foregroundColor=COLORS["text"],
            chromeBackgroundColor=COLORS["bg_card"],
            headerBackgroundColor=COLORS["bg_card"],
            headerTextColor=COLORS["text_secondary"],
            headerFontSize=11,
            headerFontWeight=600,
            borderColor=COLORS["border_light"],
            rowBorder={"style": "solid", "width": 1, "color": COLORS["border_light"]},
            columnBorder=False,
            oddRowBackgroundColor="#0E131A",
            rowHoverColor=COLORS["bg_surface"],
            selectedRowBackgroundColor=COLORS["bg_surface"],
            accentColor=COLORS["primary"],
            fontFamily="Inter, -apple-system, sans-serif",
            fontSize=13,
            rowHeight=34,
            headerHeight=36,
            cellHorizontalPadding=12,
            wrapperBorderRadius=10,
            wrapperBorder={"style": "solid", "width": 1, "color": COLORS["border"]},
        )
    )


_MONO = "'JetBrains Mono', 'SF Mono', Menlo, monospace"

# CSS injected into the grid iframe (global page CSS can't reach it).
_AGGRID_CSS = {
    "::-webkit-scrollbar": {"width": "8px !important", "height": "8px !important"},
    "::-webkit-scrollbar-track": {"background": COLORS["bg"] + " !important"},
    "::-webkit-scrollbar-thumb": {"background": COLORS["border"] + " !important", "border-radius": "4px !important"},
    "::-webkit-scrollbar-thumb:hover": {"background": "#484F58 !important"},
    ".ag-body-horizontal-scroll-viewport, .ag-body-vertical-scroll-viewport": {
        "scrollbar-width": "thin", "scrollbar-color": COLORS["border"] + " " + COLORS["bg"],
    },
    ".ag-header-cell-text": {
        "text-transform": "uppercase", "letter-spacing": "0.06em", "font-size": "11px",
        "font-weight": "600", "white-space": "normal", "line-height": "1.2",
    },
    ".ag-header-cell": {"border-bottom": "1px solid " + COLORS["border"] + " !important"},
    ".ag-right-aligned-header .ag-header-cell-label": {"flex-direction": "row-reverse"},
    ".ag-row-pinned": {
        "background": COLORS["bg_card"] + " !important", "font-weight": "600",
        "border-top": "2px solid " + COLORS["border"] + " !important",
    },
    ".ag-cell": {"overflow": "hidden", "text-overflow": "ellipsis", "white-space": "nowrap"},
    ".ag-cell-focus": {"border-color": "transparent !important"},
}


def display_aggrid(df, columns: dict | None = None, height: int = TABLE_HEIGHT,
                   pin_left: list[str] | None = None, totals: dict | None = None):
    """Render a DataFrame as an AG-Grid table with the Kodak theme.

    `columns` maps column-name -> spec dict:
        {"label": str            display header (defaults to the column name),
         "help": str             header tooltip,
         "type": "currency"|"percent"|"number"|"quantity"|"text"|"progress",
         "decimals": int,
         "color_signed": bool    green if >0, red if <0,
         "max": float            only for type="progress",
         "width": int            minimum width; columns then stretch to fill the grid}
    `totals` maps column-name -> value for a pinned bottom row (e.g. sums).
    """
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

    columns = columns or {}
    pin_left = pin_left or []
    gb = GridOptionsBuilder.from_dataframe(df)

    gb.configure_default_column(
        resizable=True, sortable=True, filter=True, floatingFilter=False,
        suppressHeaderFilterButton=True, minWidth=80,
        cellStyle={"fontFamily": "Inter, -apple-system, sans-serif"},
    )

    guard = ("  if (params.value === null || params.value === undefined || isNaN(params.value)) return '';")

    def num_formatter(decimals: int) -> JsCode:
        return JsCode("function(params){" + guard +
                      "  return Number(params.value).toLocaleString('nb-NO', {minimumFractionDigits:%d, maximumFractionDigits:%d});}" % (decimals, decimals))

    def pct_formatter(decimals: int) -> JsCode:
        return JsCode("function(params){" + guard +
                      "  return Number(params.value).toLocaleString('nb-NO', {minimumFractionDigits:%d, maximumFractionDigits:%d}) + ' %%';}" % (decimals, decimals))

    def qty_formatter(max_decimals: int) -> JsCode:
        return JsCode("function(params){" + guard +
                      "  return Number(params.value).toLocaleString('nb-NO', {minimumFractionDigits:0, maximumFractionDigits:%d});}" % max_decimals)

    def progress_cell_style(max_val: float) -> JsCode:
        return JsCode(
            "function(params){"
            "  const v = Number(params.value) || 0;"
            "  const pct = Math.max(0, Math.min(100, (v / %s) * 100));" % max_val +
            "  return {"
            "    background: 'linear-gradient(to right, rgba(102,126,234,0.45) 0%, rgba(118,75,162,0.45) ' + pct + '%, transparent ' + pct + '%)',"
            "    color: '" + COLORS["text"] + "', fontFamily: \"" + _MONO + "\", fontSize: '12.5px',"
            "  };"
            "}"
        )

    signed_color = JsCode(
        "function(params){"
        "  const base = {fontFamily: \"" + _MONO + "\", fontSize: '12.5px'};"
        "  const v = Number(params.value);"
        "  if (isNaN(v) || params.node.rowPinned) return base;"
        "  if (v > 0) return Object.assign(base, {color: '" + COLORS["positive"] + "', fontWeight: '600'});"
        "  if (v < 0) return Object.assign(base, {color: '" + COLORS["negative"] + "', fontWeight: '600'});"
        "  return Object.assign(base, {color: '" + COLORS["text_secondary"] + "'});"
        "}"
    )
    mono_style = {"fontFamily": _MONO, "fontSize": "12.5px"}

    for col, spec in columns.items():
        if col not in df.columns:
            continue
        kwargs = {"headerName": spec.get("label", col), "minWidth": spec.get("width", 80)}
        if spec.get("help"):
            kwargs["headerTooltip"] = spec["help"]
        if spec.get("tooltip_field") and spec["tooltip_field"] in df.columns:
            kwargs["tooltipField"] = spec["tooltip_field"]
        if spec.get("hide"):
            kwargs["hide"] = True
        if col in pin_left:
            kwargs["pinned"] = "left"

        ctype = spec.get("type", "text")
        decimals = spec.get("decimals", 0)
        color_signed = spec.get("color_signed", False)

        if ctype in ("currency", "number"):
            kwargs.update(valueFormatter=num_formatter(decimals), type="rightAligned",
                          cellStyle=signed_color if color_signed else mono_style)
        elif ctype == "quantity":
            kwargs.update(valueFormatter=qty_formatter(spec.get("decimals", 4)), type="rightAligned",
                          cellStyle=mono_style)
        elif ctype == "percent":
            kwargs.update(valueFormatter=pct_formatter(decimals), type="rightAligned",
                          cellStyle=signed_color if color_signed else mono_style)
        elif ctype == "progress":
            kwargs.update(valueFormatter=pct_formatter(decimals if decimals else 1),
                          cellStyle=progress_cell_style(spec.get("max", 100)), type="rightAligned")
        elif color_signed:
            kwargs["cellStyle"] = signed_color

        gb.configure_column(col, **kwargs)

    for col in pin_left:
        if col in df.columns and col not in columns:
            gb.configure_column(col, pinned="left")

    grid_options = gb.build()
    grid_options["autoSizeStrategy"] = {"type": "fitGridWidth"}
    grid_options["suppressCellFocus"] = True
    grid_options["enableCellTextSelection"] = True
    grid_options["tooltipShowDelay"] = 300
    if totals:
        grid_options["pinnedBottomRowData"] = [{c: totals.get(c) for c in df.columns}]

    # Never taller than the content: a short table should not sit in an empty box.
    content_height = 36 + 34 * max(len(df), 1) + (34 if totals else 0) + 8
    height = min(height, content_height)

    return AgGrid(
        df,
        gridOptions=grid_options,
        theme=_kodak_aggrid_theme(),
        height=height,
        allow_unsafe_jscode=True,
        update_mode="NO_UPDATE",
        custom_css=_AGGRID_CSS,
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


def render_chart(fig: go.Figure, **kwargs):
    """Theme + render a Plotly figure full-width (Streamlit's own theme off).

    The modebar is hidden: on touch screens Plotly shows it permanently,
    covering the top of every chart, and nobody exports PNGs from here.
    """
    apply_plotly_theme(fig)
    config = {"displayModeBar": False, "responsive": True, "scrollZoom": False}
    st.plotly_chart(fig, width="stretch", theme=None, config=config, **kwargs)


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
