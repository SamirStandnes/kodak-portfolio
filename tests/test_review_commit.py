"""Tests for kodak/pipeline/review_commit.py helpers."""
import pytest

from kodak.pipeline.review_commit import _looks_like_name


class TestLooksLikeName:
    """`_looks_like_name` must flag broker display names so they don't land in
    the symbol column (where Yahoo can't price them)."""

    @pytest.mark.parametrize("ticker", [
        "AMZN", "MSFT", "ADBE", "SPCX", "FND", "BRK-B",
        "AENA.MC", "XCS3.DE", "D05.SI", "2318.HK", "3350.T", "0P0001K6NJ.IR",
    ])
    def test_real_tickers_are_not_names(self, ticker):
        assert _looks_like_name(ticker) is False

    @pytest.mark.parametrize("name", [
        "Adobe", "SpaceX", "Tesla",                      # single-word names
        "Xtrackers MSCI Malaysia UCITS ETF 1C",          # multi-word names
        "DBS Group Holdings Ltd.",
    ])
    def test_display_names_are_flagged(self, name):
        assert _looks_like_name(name) is True

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_values_are_not_names(self, empty):
        assert _looks_like_name(empty) is False
