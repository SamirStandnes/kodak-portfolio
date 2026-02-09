import streamlit as st

# --- COLOR PALETTE (GitHub-dark inspired) ---
COLORS = {
    "primary": "#667EEA",
    "secondary": "#764BA2",
    "bg": "#0E1117",
    "bg_card": "#161B22",
    "bg_surface": "#1C2333",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "border": "#30363D",
    "border_light": "#21262D",
    "green": "#3FB950",
    "red": "#F85149",
    "yellow": "#D29922",
    "blue": "#58A6FF",
    "purple": "#BC8CFF",
    "pink": "#F778BA",
}

CHART_COLORS = [
    "#667EEA", "#58A6FF", "#3FB950", "#D29922",
    "#F85149", "#BC8CFF", "#F778BA", "#79C0FF",
]


def apply_theme():
    """Inject custom CSS and sidebar branding. Call once after set_page_config()."""
    st.markdown(_CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 0.25rem 0 0.25rem 0;">
            <h2 style="margin: 0; font-size: 1.4rem; font-weight: 800;
                       background: linear-gradient(135deg, #667EEA 0%, #764BA2 100%);
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                       background-clip: text; letter-spacing: 0.1em;">KODAK</h2>
            <p style="color: #8B949E; font-size: 0.7rem; margin: 0;
                      letter-spacing: 0.15em; text-transform: uppercase;">Portfolio Tracker</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<hr style='margin: 0.5rem 0 !important;'>", unsafe_allow_html=True)


def page_header(title, description=""):
    """Render a gradient page header."""
    desc_html = (
        f'<p style="color: #8B949E; margin: 0.5rem 0 0 0; font-size: 1rem;">{description}</p>'
        if description else ''
    )
    st.markdown(f"""
    <div style="padding: 0 0 1.5rem 0;">
        <h1 style="margin: 0; font-size: 2.2rem; font-weight: 700;
                   background: linear-gradient(135deg, #667EEA 0%, #764BA2 100%);
                   -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                   background-clip: text;">{title}</h1>
        {desc_html}
    </div>
    """, unsafe_allow_html=True)


def styled_subheader(text):
    """Render a subheader with a left accent border."""
    st.markdown(f"""
    <div style="border-left: 3px solid #667EEA; padding-left: 0.75rem; margin: 1.5rem 0 1rem 0;">
        <h3 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #E6EDF3;">{text}</h3>
    </div>
    """, unsafe_allow_html=True)


def get_plotly_layout(**overrides):
    """Return a Plotly layout dict matching the dark theme."""
    layout = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E6EDF3", size=12),
        title=dict(font=dict(size=16, color="#E6EDF3")),
        xaxis=dict(
            gridcolor="#21262D",
            linecolor="#30363D",
            zerolinecolor="#30363D",
            title_font=dict(color="#8B949E"),
            tickfont=dict(color="#8B949E"),
        ),
        yaxis=dict(
            gridcolor="#21262D",
            linecolor="#30363D",
            zerolinecolor="#30363D",
            title_font=dict(color="#8B949E"),
            tickfont=dict(color="#8B949E"),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8B949E", size=11),
        ),
        margin=dict(l=40, r=40, t=60, b=40),
        hoverlabel=dict(
            bgcolor="#1C2333",
            font_size=13,
            font_color="#E6EDF3",
            bordercolor="#30363D",
        ),
        colorway=CHART_COLORS,
        hovermode="x unified",
    )
    layout.update(overrides)
    return layout


# ---------------------------------------------------------------------------
# CSS (private constant)
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ===== FADE IN ===== */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
    animation: fadeIn 0.4s ease-out;
}

/* ===== METRIC CARDS ===== */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #161B22 0%, #1C2333 100%);
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(102, 126, 234, 0.15);
}
[data-testid="stMetricLabel"] {
    font-size: 0.8rem !important;
    color: #8B949E !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 500 !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.75rem !important;
    font-weight: 700 !important;
}

/* ===== SIDEBAR ===== */
[data-testid="stSidebar"] {
    background: #0D1117;
    border-right: 1px solid #21262D;
}
[data-testid="stSidebarNavLink"] {
    border-radius: 8px !important;
    margin: 2px 8px;
    transition: background 0.2s ease;
}

/* ===== DIVIDERS ===== */
hr {
    border-color: #21262D !important;
    margin: 2rem 0 !important;
}

/* ===== DATAFRAMES ===== */
[data-testid="stDataFrame"] {
    border: 1px solid #30363D;
    border-radius: 10px;
    overflow: hidden;
}

/* ===== HEADERS ===== */
h1 { font-weight: 700 !important; letter-spacing: -0.02em; }
h2, h3 { color: #E6EDF3 !important; font-weight: 600 !important; letter-spacing: -0.01em; }

/* ===== BUTTONS ===== */
.stButton > button {
    border-radius: 8px !important;
    padding: 0.5rem 1.5rem !important;
    font-weight: 500 !important;
    border: 1px solid #30363D !important;
    transition: all 0.2s ease !important;
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
::-webkit-scrollbar-track { background: #0E1117; }
::-webkit-scrollbar-thumb { background: #30363D; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484F58; }
</style>
"""
