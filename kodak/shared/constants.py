"""Centralized constants for the Kodak portfolio system.

Theme constants (COLORS, PLOTLY_LAYOUT) are re-exported from
kodak.dashboard.style — that module is the single source of truth.
"""

# Dashboard
CACHE_TTL = 1800  # 30 minutes — portfolio data refreshes once daily (price
# cron at 22:00 UTC), so a long TTL keeps the dashboard warm and avoids
# re-querying Neon cross-region on every visit. Bump down if data feels stale.
TABLE_HEIGHT = 600
MIN_QUANTITY_THRESHOLD = 0.001

# Re-export theme — kept here so non-dashboard code (CLIs, scripts) can
# import COLORS without depending on streamlit being importable.
try:
    from kodak.dashboard.style import COLORS, PLOTLY_LAYOUT
except ImportError:
    # Streamlit not available (e.g. running CLI in a stripped env) — provide a
    # minimal fallback so non-UI imports still succeed.
    COLORS = {
        "primary": "#667EEA", "positive": "#3FB950", "negative": "#F85149",
        "warning": "#D29922", "purple": "#BC8CFF", "neutral": "#8B949E",
        "light_blue": "#58A6FF", "text_muted": "#8B949E",
    }
    PLOTLY_LAYOUT = {}
