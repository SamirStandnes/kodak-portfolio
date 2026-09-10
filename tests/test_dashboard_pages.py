"""Smoke-run every dashboard page headlessly via Streamlit's AppTest.

Catches the class of bug a unit test never sees: a page that imports fine but
raises at render time (missing column after a refactor, deprecated Streamlit
argument, SQL that only works on one backend, ...).

Needs the real local database (database/portfolio.db, gitignored) and, for
the Dividends / Performance pages, network access to Yahoo Finance — so it is
skipped automatically where the database is absent (e.g. CI).
"""
import glob
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "portfolio.db"
PAGES = sorted(p for p in glob.glob(str(ROOT / "kodak" / "dashboard" / "_pages" / "*.py"))
               if not p.endswith("__init__.py"))

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists() or os.environ.get("DATABASE_URL"),
    reason="dashboard smoke test needs the local SQLite database",
)


@pytest.mark.parametrize("page", PAGES, ids=[Path(p).stem for p in PAGES])
def test_page_renders_without_exception(page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(page, default_timeout=300)
    at.run()

    assert not at.exception, "\n".join(
        f"{e.type}: {e.message}\n" + "\n".join(e.stack_trace[-8:]) for e in at.exception
    )
    assert not at.error, [e.value for e in at.error]
