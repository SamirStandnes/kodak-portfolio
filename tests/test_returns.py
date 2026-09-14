"""Tests for kodak/shared/returns.py (pure math) and the benchmark comparison."""
import pandas as pd
import pytest

from kodak.shared import returns as R
import kodak.shared.benchmarks as B
from tests.test_valuation import temp_db, run, add_fx  # noqa: F401  (fixture reuse)


def days(*items):
    return pd.DatetimeIndex([pd.Timestamp(d) for d in items])


class TestGrowthIndex:

    def test_flow_on_a_day_earns_no_return_that_day(self):
        idx = days("2026-01-01", "2026-01-02", "2026-01-03")
        values = pd.Series([1000.0, 2100.0, 2310.0], index=idx)     # +1000 deposit on day 2, then +10%
        flows = pd.Series([1000.0, 1000.0, 0.0], index=idx)
        g = R.growth_index(values, flows)
        # day 2: (2100 - 1000) / 1000 = +10%, day 3: 2310 / 2100 = +10%
        assert g.tolist() == pytest.approx([1.0, 1.10, 1.21])

    def test_withdrawal_does_not_count_as_a_loss(self):
        idx = days("2026-01-01", "2026-01-02")
        values = pd.Series([1000.0, 500.0], index=idx)
        flows = pd.Series([1000.0, -500.0], index=idx)
        assert R.growth_index(values, flows).iloc[-1] == pytest.approx(1.0)

    def test_starts_flat_before_capital_exists(self):
        idx = days("2026-01-01", "2026-01-02", "2026-01-03")
        values = pd.Series([0.0, 1000.0, 1100.0], index=idx)
        flows = pd.Series([0.0, 1000.0, 0.0], index=idx)
        assert R.growth_index(values, flows).tolist() == pytest.approx([1.0, 1.0, 1.10])

    def test_big_deposit_before_a_good_year_does_not_inflate_twr(self):
        """The whole point vs XIRR: timing of money must not matter."""
        idx = days("2026-01-01", "2026-01-02", "2026-01-03")
        small_first = R.growth_index(pd.Series([100.0, 10110.0, 11121.0], index=idx),
                                     pd.Series([100.0, 10000.0, 0.0], index=idx))
        big_first = R.growth_index(pd.Series([10000.0, 11100.0, 12210.0], index=idx),
                                   pd.Series([10000.0, 100.0, 0.0], index=idx))
        assert small_first.iloc[-1] == pytest.approx(big_first.iloc[-1])


class TestHelpers:

    def test_annualized(self):
        assert R.annualized(1.21, 730.5) == pytest.approx(0.10, rel=1e-3)
        assert R.annualized(1.0, 0) is None

    def test_yearly_returns_use_previous_year_end(self):
        idx = days("2025-06-01", "2025-12-31", "2026-06-30")
        g = pd.Series([1.0, 1.2, 1.5], index=idx)
        y = R.yearly_returns(g)
        assert y.loc[2025] == pytest.approx(0.2)
        assert y.loc[2026] == pytest.approx(0.25)

    def test_rebase_carries_prices_forward_and_scales(self):
        prices = pd.Series([10.0, 12.0], index=days("2026-01-01", "2026-01-03"))
        out = R.rebase(prices, days("2026-01-01", "2026-01-02", "2026-01-03"), 100.0)
        assert out.tolist() == pytest.approx([100.0, 100.0, 120.0])


class TestShadowPortfolio:

    def test_same_flows_in_a_flat_index_return_the_money(self):
        idx = days("2026-01-01", "2026-06-01", "2026-12-31")
        flows = pd.Series([1000.0, 500.0, 0.0], index=idx)
        prices = pd.Series([10.0, 10.0, 10.0], index=idx)
        sh = R.shadow_portfolio(flows, prices)
        assert sh.final_value == pytest.approx(1500.0)
        assert sh.xirr_pct == pytest.approx(0.0, abs=1e-6)

    def test_index_doubling_doubles_the_units_value(self):
        idx = days("2026-01-01", "2026-12-31")
        sh = R.shadow_portfolio(pd.Series([1000.0, 0.0], index=idx), pd.Series([10.0, 20.0], index=idx))
        assert sh.final_value == pytest.approx(2000.0)
        assert sh.xirr_pct == pytest.approx(100.0, rel=0.02)

    def test_withdrawal_sells_units(self):
        idx = days("2026-01-01", "2026-06-01")
        sh = R.shadow_portfolio(pd.Series([1000.0, -500.0], index=idx), pd.Series([10.0, 10.0], index=idx))
        assert sh.final_value == pytest.approx(500.0)


class TestBenchmarkComparison:

    def test_compare_converts_currency_and_builds_growth(self, temp_db, monkeypatch):
        monkeypatch.setattr(B, "BASE_CURRENCY", "NOK")
        run(temp_db, "INSERT INTO benchmarks (code, name, symbol, currency) VALUES ('IDX', 'Index', 'X', 'USD')")
        for d, c in (("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 121.0)):
            run(temp_db, "INSERT INTO benchmark_prices (code, date, close) VALUES ('IDX', ?, ?)", (d, c))
        for d in ("2026-01-01", "2026-01-02", "2026-01-03"):
            add_fx(temp_db, "USD", d, 10.0)
        history = pd.DataFrame({
            'date': pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            'holdings_value': [1000.0, 1050.0, 1100.0], 'cash': [0.0, 0.0, 0.0],
            'total_value': [1000.0, 1050.0, 1100.0], 'net_deposits': [1000.0, 1000.0, 1000.0],
        })
        bench = [B.Benchmark('IDX', 'Index', 'X', 'USD')]
        cmp = B.compare_to_benchmarks(history, portfolio_xirr_pct=12.0, benchmarks=bench)
        assert cmp is not None
        assert cmp.growth['Portfolio'].tolist() == pytest.approx([100.0, 105.0, 110.0])
        assert cmp.growth['Index'].tolist() == pytest.approx([100.0, 110.0, 121.0])
        row = cmp.shadow.iloc[0]
        assert row['index_value'] == pytest.approx(1210.0)      # 1000 NOK bought 1 unit at 1000 NOK, now 1210
        assert row['difference'] == pytest.approx(1100.0 - 1210.0)
        assert cmp.missing == []

    def test_missing_benchmark_is_reported_not_fatal(self, temp_db, monkeypatch):
        monkeypatch.setattr(B, "BASE_CURRENCY", "NOK")
        history = pd.DataFrame({
            'date': pd.to_datetime(["2026-01-01", "2026-01-02"]),
            'holdings_value': [1000.0, 1100.0], 'cash': [0.0, 0.0],
            'total_value': [1000.0, 1100.0], 'net_deposits': [1000.0, 1000.0],
        })
        cmp = B.compare_to_benchmarks(history, benchmarks=[B.Benchmark('NONE', 'Nothing', 'N', 'NOK')])
        assert cmp.missing == ['Nothing']
        assert list(cmp.growth.columns) == ['Portfolio']
