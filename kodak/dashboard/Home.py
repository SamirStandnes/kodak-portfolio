"""Kodak dashboard entry point.

Acts as a router: gates auth before any page is registered, then builds
st.navigation explicitly so the auto-discovery in `pages/` doesn't leak
the menu before login.
"""
import sys
from pathlib import Path
root_path = str(Path(__file__).resolve().parent.parent.parent)
if root_path not in sys.path:
    sys.path.append(root_path)

import streamlit as st
from kodak.dashboard.common import check_auth

check_auth()

st.set_page_config(
    page_title="Kodak Portfolio", page_icon="📈",
    layout="wide", initial_sidebar_state="expanded",
)

_PAGES_DIR = Path(__file__).parent / "_pages"

nav = st.navigation([
    st.Page(str(_PAGES_DIR / "0_Overview.py"),    title="Overview",    icon="📈", default=True),
    st.Page(str(_PAGES_DIR / "1_Holdings.py"),    title="Holdings",    icon="🏦"),
    st.Page(str(_PAGES_DIR / "2_Dividends.py"),   title="Dividends",   icon="💰"),
    st.Page(str(_PAGES_DIR / "3_Interest.py"),    title="Interest",    icon="💳"),
    st.Page(str(_PAGES_DIR / "4_Fees.py"),        title="Fees",        icon="💸"),
    st.Page(str(_PAGES_DIR / "5_Activity.py"),    title="Activity",    icon="📝"),
    st.Page(str(_PAGES_DIR / "6_FX_Analysis.py"), title="FX Analysis", icon="💱"),
    st.Page(str(_PAGES_DIR / "7_Performance.py"), title="Performance", icon="📊"),
    st.Page(str(_PAGES_DIR / "8_Risk.py"),        title="Risk",        icon="⚠️"),
    st.Page(str(_PAGES_DIR / "99_System.py"),     title="System",      icon="⚙️"),
])

nav.run()
