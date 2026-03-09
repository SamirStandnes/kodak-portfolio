"""Centralized constants for the Kodak portfolio system."""

# Dashboard
CACHE_TTL = 300  # 5 minutes
TABLE_HEIGHT = 600
MIN_QUANTITY_THRESHOLD = 0.001

# Colors — consistent palette across all charts
COLORS = {
    "primary": "#4A90D9",       # Blue — main accent, equity bars
    "positive": "#27AE60",      # Green — gains, dividends
    "negative": "#E74C3C",      # Red — losses, fees
    "warning": "#F39C12",       # Amber — warnings, fee efficiency
    "purple": "#8E44AD",        # Purple — platform fees, secondary
    "neutral": "#95A5A6",       # Grey — neutral data
    "light_blue": "#5DADE2",    # Light blue — bars, secondary charts
    "text_muted": "#AAB2BD",    # Muted text
}

# Plotly chart defaults
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#FAFAFA", size=13),
    margin=dict(l=40, r=40, t=50, b=40),
    hovermode="x unified",
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
    ),
)
