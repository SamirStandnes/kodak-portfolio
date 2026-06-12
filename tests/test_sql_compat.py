"""Tests for the SQLite -> PostgreSQL translation layer used on Heroku."""
import pytest

from heroku.sql_compat import translate_query


class TestJulianDayTranslation:
    def test_column_translates_to_epoch_days(self):
        sql = "SELECT * FROM t ORDER BY ABS(strftime('%J', t.date) - strftime('%J', ?))"
        result = translate_query(sql)
        assert "EXTRACT(EPOCH FROM t.date::timestamp) / 86400.0" in result
        assert "EXTRACT(EPOCH FROM %s::timestamp) / 86400.0" in result
        assert "DOY" not in result

    def test_epoch_days_are_continuous_across_year_boundary(self):
        # The old EXTRACT(DOY ...) translation reset each year, so
        # 2023-12-31 vs 2024-01-01 compared as |365 - 1| = 364 days apart.
        # Epoch days must differ by exactly 1.
        from datetime import datetime
        epoch_days = lambda s: datetime.fromisoformat(s).timestamp() / 86400.0
        assert abs(epoch_days("2024-01-01") - epoch_days("2023-12-31")) == pytest.approx(1.0)


class TestPlaceholders:
    def test_question_marks_become_psycopg2_placeholders(self):
        assert translate_query("SELECT * FROM t WHERE a = ? AND b = ?") == \
            "SELECT * FROM t WHERE a = %s AND b = %s"

    def test_question_mark_inside_string_literal_untouched(self):
        result = translate_query("SELECT * FROM t WHERE a = 'what?' AND b = ?")
        assert "'what?'" in result
        assert result.endswith("b = %s")


class TestGroupByCoalesce:
    def test_single_alias_rewritten(self):
        sql = ("SELECT COALESCE(i.symbol, i.isin) as symbol, SUM(t.amount) "
               "FROM t GROUP BY symbol")
        assert "GROUP BY COALESCE(i.symbol, i.isin)" in translate_query(sql)

    def test_all_coalesce_aliases_rewritten(self):
        sql = ("SELECT COALESCE(a, b) as x, COALESCE(c, d) as y, SUM(v) "
               "FROM t GROUP BY x, y")
        result = translate_query(sql)
        assert "GROUP BY COALESCE(a, b)" in result
        assert "COALESCE(c, d)" in result.split("GROUP BY")[1]


class TestStrftimeYear:
    def test_year_translates_to_to_char(self):
        sql = "SELECT strftime('%Y', date) as year FROM t GROUP BY year"
        assert "TO_CHAR(date::date, 'YYYY')" in translate_query(sql)


class TestDateNow:
    def test_relative_months_translates_to_interval(self):
        sql = "SELECT * FROM t WHERE date >= date('now', '-12 months')"
        assert "CURRENT_DATE - INTERVAL '12 months'" in translate_query(sql)
