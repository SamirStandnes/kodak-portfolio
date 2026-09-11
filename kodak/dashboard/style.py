"""
Canonical theme for the Kodak dashboard.

Single source of truth for colors, Plotly layout, and Streamlit CSS.
Pages and other modules import COLORS / PLOTLY_LAYOUT from
kodak.shared.constants (which re-exports from here for backwards compatibility).
"""

import streamlit as st


# ---------------------------------------------------------------------------
# COLOR PALETTE
# Modern dark — GitHub-dark inspired, polished for finance dashboards.
# Both semantic keys (positive/negative/warning) and named keys (green/red/yellow)
# are exposed so existing page imports keep working.
# ---------------------------------------------------------------------------
COLORS = {
    # Surfaces
    "bg":             "#0B0E13",
    "bg_card":        "#161B22",
    "bg_surface":     "#1C2333",
    "border":         "#30363D",
    "border_light":   "#21262D",

    # Text
    "text":           "#E6EDF3",
    "text_secondary": "#8B949E",
    "text_muted":     "#8B949E",
    "neutral":        "#8B949E",

    # Accents — gradient
    "primary":        "#667EEA",
    "secondary":      "#764BA2",

    # Semantic financial
    "positive":       "#3FB950",
    "negative":       "#F85149",
    "warning":        "#D29922",

    # Extended palette + aliases
    "blue":           "#58A6FF",
    "light_blue":     "#58A6FF",
    "green":          "#3FB950",
    "red":            "#F85149",
    "yellow":         "#D29922",
    "purple":         "#BC8CFF",
    "pink":           "#F778BA",
}


CHART_COLORS = [
    COLORS["primary"], COLORS["blue"], COLORS["positive"], COLORS["yellow"],
    COLORS["negative"], COLORS["purple"], COLORS["pink"], "#79C0FF",
]


# ---------------------------------------------------------------------------
# PLOTLY LAYOUT
# ---------------------------------------------------------------------------
def get_plotly_layout(**overrides) -> dict:
    """Return the canonical Plotly layout dict, with optional overrides merged in."""
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="'Inter', -apple-system, sans-serif",
            color=COLORS["text"],
            size=12,
        ),
        xaxis=dict(
            gridcolor="rgba(48,54,61,0.45)",
            linecolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            automargin=True,
            title_font=dict(color=COLORS["text_secondary"], size=11),
            tickfont=dict(color=COLORS["text_secondary"], size=11, family="'JetBrains Mono', monospace"),
        ),
        yaxis=dict(
            gridcolor="rgba(48,54,61,0.45)",
            linecolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            automargin=True,
            title_font=dict(color=COLORS["text_secondary"], size=11),
            tickfont=dict(color=COLORS["text_secondary"], size=11, family="'JetBrains Mono', monospace"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLORS["text_secondary"], size=11),
        ),
        margin=dict(l=48, r=24, t=48, b=40),
        hoverlabel=dict(
            bgcolor=COLORS["bg_surface"],
            font_size=13,
            font_color=COLORS["text"],
            bordercolor=COLORS["border"],
            font_family="'JetBrains Mono', monospace",
        ),
        colorway=CHART_COLORS,
        hovermode="x unified",
    )
    layout.update(overrides)
    return layout


PLOTLY_LAYOUT = get_plotly_layout()


# ---------------------------------------------------------------------------
# THEME APPLICATION
# Called from common.page_setup() after st.set_page_config().
# ---------------------------------------------------------------------------
def apply_theme():
    """Inject custom CSS, fonts, and sidebar branding."""
    st.markdown(_FONTS_AND_CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown(
            """
            <div style="text-align: center; padding: 0.5rem 0 0.25rem 0;">
                <h2 style="margin: 0; font-size: 1.5rem; font-weight: 800;
                           font-family: 'Inter', sans-serif;
                           background: linear-gradient(135deg, #667EEA 0%, #764BA2 100%);
                           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                           background-clip: text; letter-spacing: 0.18em;">KODAK</h2>
                <p style="color: #8B949E; font-size: 0.65rem; margin: 2px 0 0 0;
                          letter-spacing: 0.2em; text-transform: uppercase;
                          font-family: 'JetBrains Mono', monospace;">Portfolio · v3</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<hr style='margin: 0.5rem 0 !important;'>", unsafe_allow_html=True)


def page_header(title: str, icon: str = "", description: str = ""):
    """Gradient page title with a plain (un-clipped) icon and optional subtitle."""
    icon_html = (
        f'<span style="font-size: 1.6rem; line-height: 1; margin-right: 0.6rem;">{icon}</span>'
        if icon else ''
    )
    desc_html = (
        f'<p style="color: {COLORS["text_secondary"]}; margin: 0.35rem 0 0 0; font-size: 0.95rem; '
        f'font-family: Inter, sans-serif;">{description}</p>'
        if description else ''
    )
    st.markdown(
        f"""
        <div class="kodak-page-header" style="padding: 0 0 1.1rem 0; border-bottom: 1px solid {COLORS['border_light']}; margin-bottom: 1.4rem;">
            <div style="display: flex; align-items: center;">
                {icon_html}
                <h1 style="margin: 0; font-size: 1.9rem; font-weight: 800;
                           font-family: 'Inter', sans-serif; letter-spacing: -0.02em;
                           background: linear-gradient(135deg, #7F8FF0 0%, #A57BD6 100%);
                           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                           background-clip: text;">{title}</h1>
            </div>
            {desc_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def styled_subheader(text: str):
    """Subheader with a gradient left accent."""
    st.markdown(
        f"""
        <div style="border-left: 3px solid #667EEA; padding-left: 0.75rem; margin: 1.5rem 0 1rem 0;">
            <h3 style="margin: 0; font-size: 1.15rem; font-weight: 600;
                       font-family: 'Inter', sans-serif; color: #E6EDF3;
                       letter-spacing: -0.01em;">{text}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# CSS — fonts + theme overrides
# ---------------------------------------------------------------------------
_FONTS_AND_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<style>
/* ===== GLOBAL TYPOGRAPHY ===== */
html, body, [class*="css"], .stApp, .block-container {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    letter-spacing: -0.005em;
}

/* Tabular numbers — JetBrains Mono for any element with a financial-number role */
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"],
.stDataFrame td,
.stDataFrame [data-testid="StyledDataFrameDataCell"],
.dvn-scroller [role="gridcell"] {
    font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace !important;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}

/* ===== FADE IN ===== */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    animation: fadeIn 0.35s ease-out;
    max-width: 1400px;
}

/* ===== METRIC CARDS ===== */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #161B22 0%, #1C2333 100%);
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 0.9rem 1.15rem;
    min-height: 118px;              /* cards with and without a delta line up */
    box-sizing: border-box;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    border-color: #667EEA;
    box-shadow: 0 6px 18px rgba(102, 126, 234, 0.15);
}
[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.7rem !important;
    font-weight: 700 !important;
    color: #E6EDF3 !important;
    letter-spacing: -0.02em;
    line-height: 1.15;
}
[data-testid="stMetricDelta"] {
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    margin-top: 0.35rem;
}

/* ===== SIDEBAR ===== */
[data-testid="stSidebar"] {
    background: #0B0E13;
    border-right: 1px solid #21262D;
}
[data-testid="stSidebarNavLink"] {
    border-radius: 8px !important;
    margin: 1px 8px;
    padding-top: 0.35rem !important;
    padding-bottom: 0.35rem !important;
    transition: background 0.15s ease;
}
[data-testid="stSidebarNavLink"] span { font-size: 0.9rem; }

/* ===== DIVIDERS ===== */
hr {
    border-color: #21262D !important;
    margin: 1.25rem 0 !important;
}

/* ===== DATAFRAMES ===== */
[data-testid="stDataFrame"] {
    border: 1px solid #30363D;
    border-radius: 10px;
    overflow: hidden;
}
[data-testid="stDataFrame"] thead tr th {
    background: #1C2333 !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    border-bottom: 1px solid #30363D !important;
}

/* ===== HEADERS ===== */
h1 {
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.025em;
    color: #E6EDF3 !important;
}
h2, h3 {
    font-family: 'Inter', sans-serif !important;
    color: #E6EDF3 !important;
    font-weight: 600 !important;
    letter-spacing: -0.015em;
}
[data-testid="stHeadingWithActionElements"] h3 {
    font-size: 1.15rem !important;
    padding-bottom: 0.25rem;
}

/* ===== INPUTS ===== */
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div > div,
[data-testid="stTextInput"] > div > div,
[data-testid="stDateInput"] > div > div {
    border-radius: 8px !important;
    border-color: #30363D !important;
    background: #161B22 !important;
}
[data-testid="stWidgetLabel"] p {
    font-size: 0.72rem !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 600;
}
[data-testid="stCaptionContainer"] p { color: #8B949E; font-size: 0.82rem; }

/* ===== BORDERED CONTAINERS ===== */
[data-testid="stVerticalBlockBorderWrapper"] > div[style*="border"] {
    border-radius: 12px !important;
    border-color: #21262D !important;
    background: #0E131A;
}

/* ===== TABS ===== */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid #21262D;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px 8px 0 0;
    padding: 8px 16px;
    color: #8B949E;
    font-weight: 500;
}
.stTabs [aria-selected="true"] {
    color: #E6EDF3 !important;
    background: rgba(102, 126, 234, 0.08);
    border-bottom: 2px solid #667EEA !important;
}

/* ===== BUTTONS ===== */
.stButton > button {
    border-radius: 8px !important;
    padding: 0.5rem 1.5rem !important;
    font-weight: 500 !important;
    border: 1px solid #30363D !important;
    transition: all 0.2s ease !important;
    font-family: 'Inter', sans-serif !important;
}
.stButton > button:hover {
    border-color: #667EEA !important;
    box-shadow: 0 0 16px rgba(102, 126, 234, 0.2) !important;
}

/* ===== EXPANDERS ===== */
[data-testid="stExpander"] {
    border: 1px solid #30363D !important;
    border-radius: 10px !important;
    background: #161B22;
}

/* ===== ALERTS ===== */
.stAlert { border-radius: 10px !important; }

/* ===== PLOTLY CHART WRAPPERS ===== */
.js-plotly-plot { border-radius: 10px; overflow: hidden; }

/* ===== SCROLLBAR ===== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #0B0E13; }
::-webkit-scrollbar-thumb { background: #30363D; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484F58; }

/* Hide default Streamlit chrome */
#MainMenu, footer { visibility: hidden; }
header [data-testid="stHeader"] { background: transparent; }

/* ===== PHONE (≤ 640px) =====
   Streamlit stacks every column to one per row on narrow screens, which turns
   a row of metric cards into a long scroll. Lay metric rows out two per row,
   shrink the cards and the header, and trim the side padding. */
@media (max-width: 640px) {
    .block-container {
        padding-left: 0.9rem !important;
        padding-right: 0.9rem !important;
        padding-top: 3.25rem !important;   /* clear the collapsed-sidebar toggle bar */
    }
    /* metric rows: 2 per row (a row holding a chart/table keeps stacking) */
    [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
        flex-direction: row !important;
        flex-wrap: wrap !important;
        gap: 0.5rem !important;
    }
    [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
        flex: 1 1 calc(50% - 0.5rem) !important;
        width: calc(50% - 0.5rem) !important;
        min-width: calc(50% - 0.5rem) !important;
    }
    [data-testid="stMetric"] {
        min-height: 88px;
        padding: 0.6rem 0.75rem;
        border-radius: 10px;
    }
    [data-testid="stMetricLabel"] { font-size: 0.6rem !important; letter-spacing: 0.05em; }
    [data-testid="stMetricLabel"] p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    [data-testid="stMetricValue"] { font-size: 1.25rem !important; }
    [data-testid="stMetricDelta"] { font-size: 0.7rem !important; margin-top: 0.2rem; }
    /* page header */
    .kodak-page-header h1 { font-size: 1.45rem !important; }
    .kodak-page-header p { font-size: 0.82rem !important; }
    .kodak-page-header span { font-size: 1.2rem !important; }
    [data-testid="stHeadingWithActionElements"] h3 { font-size: 1rem !important; }
    hr { margin: 0.8rem 0 !important; }
    /* tabs scroll sideways instead of wrapping */
    .stTabs [data-baseweb="tab-list"] { overflow-x: auto; flex-wrap: nowrap; }
    .stTabs [data-baseweb="tab"] { padding: 6px 10px; white-space: nowrap; }
}
</style>
"""
