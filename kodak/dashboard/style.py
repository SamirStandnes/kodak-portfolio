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
            gridcolor=COLORS["border_light"],
            linecolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            title_font=dict(color=COLORS["text_secondary"]),
            tickfont=dict(color=COLORS["text_secondary"], family="'JetBrains Mono', monospace"),
        ),
        yaxis=dict(
            gridcolor=COLORS["border_light"],
            linecolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            title_font=dict(color=COLORS["text_secondary"]),
            tickfont=dict(color=COLORS["text_secondary"], family="'JetBrains Mono', monospace"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=COLORS["text_secondary"], size=11),
        ),
        margin=dict(l=40, r=40, t=60, b=40),
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
# Injected once from the entry-point (Home.py) after st.set_page_config().
# ---------------------------------------------------------------------------
def inject_global_css():
    """Inject the global stylesheet + fonts.

    Called once from the entry-point (Home.py) before the page body renders,
    so the <style> block is first in the DOM and the theme applies on the
    initial paint — no flash of unstyled content between reruns.
    """
    st.markdown(_FONTS_AND_CSS, unsafe_allow_html=True)


def render_sidebar_brand():
    """Render the KODAK sidebar header. Called once from the entry-point."""
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
                          font-family: 'JetBrains Mono', monospace;">Portfolio · v2</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<hr style='margin: 0.5rem 0 !important;'>", unsafe_allow_html=True)


def apply_theme():
    """Backwards-compatible wrapper: inject CSS + sidebar branding together.

    Prefer calling inject_global_css() / render_sidebar_brand() once from the
    entry-point. Kept so any external caller keeps working.
    """
    inject_global_css()
    render_sidebar_brand()


def page_header(title: str, description: str = ""):
    """Render a gradient page header (replaces st.title for hero pages)."""
    desc_html = (
        f'<p style="color: #8B949E; margin: 0.5rem 0 0 0; font-size: 1rem; '
        f'font-family: \'Inter\', sans-serif;">{description}</p>'
        if description else ''
    )
    st.markdown(
        f"""
        <div style="padding: 0 0 1.5rem 0;">
            <h1 style="margin: 0; font-size: 2.4rem; font-weight: 800;
                       font-family: 'Inter', sans-serif; letter-spacing: -0.02em;
                       background: linear-gradient(135deg, #667EEA 0%, #764BA2 100%);
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                       background-clip: text;">{title}</h1>
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

/* Paint the final background immediately so there's never a flash of a
   lighter default surface before the theme settles. */
.stApp { background-color: #0B0E13; }

/* ===== FADE IN =====
   Opacity-only and short. The previous version slid the whole page up 6px
   on every rerun (each navigation / widget interaction), which read as a
   visible "jump" / stutter. A quick fade with no transform keeps the entry
   feeling smooth without re-animating layout on every interaction. */
@keyframes fadeIn {
    from { opacity: 0; }
    to   { opacity: 1; }
}
.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
    animation: fadeIn 0.15s ease-out;
    max-width: 1400px;
}

/* ===== METRIC CARDS ===== */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #161B22 0%, #1C2333 100%);
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 1rem 1.25rem;
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
    font-size: 1.85rem !important;
    font-weight: 700 !important;
    color: #E6EDF3 !important;
    letter-spacing: -0.02em;
}
[data-testid="stMetricDelta"] {
    font-size: 0.85rem !important;
    font-weight: 500 !important;
}

/* ===== SIDEBAR ===== */
[data-testid="stSidebar"] {
    background: #0B0E13;
    border-right: 1px solid #21262D;
}
[data-testid="stSidebarNavLink"] {
    border-radius: 8px !important;
    margin: 2px 8px;
    transition: background 0.15s ease;
}

/* ===== DIVIDERS ===== */
hr {
    border-color: #21262D !important;
    margin: 1.75rem 0 !important;
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
</style>
"""
