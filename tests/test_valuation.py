"""Tests for the shared valuation / history functions in calculations.py.

Uses a throwaway SQLite database with the production schema so the SQL is
exercised for real; FX lookups are stubbed so nothing touches the network.
"""
import sqlite3

import pandas as pd
import pytest

import kodak.shared.db as db
import kodak.shared.calculations as calc


SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, broker TEXT,
    currency TEXT NOT NULL DEFAULT 'NOK', type TEXT, external_id TEXT UNIQUE);
CREATE TABLE instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, isin TEXT UNIQUE, symbol TEXT, name TEXT,
    type TEXT, currency TEXT, exchange_mic TEXT, sector TEXT, region TEXT,
    country TEXT, asset_class TEXT);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, external_id TEXT UNIQUE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    instrument_id INTEGER REFERENCES instruments(id),
    date TEXT NOT NULL, type TEXT NOT NULL, quantity REAL, price REAL, amount REAL,
    currency TEXT NOT NULL, exchange_rate REAL, amount_local REAL,
    fee REAL, fee_currency TEXT, fee_local REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, notes TEXT, batch_id TEXT,
    source_file TEXT, hash TEXT);
CREATE TABLE market_prices (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id), date TEXT NOT NULL,
    close REAL, currency TEXT, source TEXT, PRIMARY KEY (instrument_id, date));
CREATE TABLE exchange_rates (
    from_currency TEXT NOT NULL, to_currency TEXT NOT NULL, date TEXT NOT NULL,
    rate REAL, PRIMARY KEY (from_currency, to_currency, date));
CREATE TABLE transactions_staging (external_id TEXT);
"""


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Empty database with the production schema, wired into kodak.shared.db."""
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO accounts (id, name, broker) VALUES (1, 'Test', 'Broker')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    # No network: USD is worth 10 base units, anything else 1:1.
    monkeypatch.setattr(calc, "get_exchange_rate",
                        lambda frm, to: 10.0 if frm == "USD" else 1.0)
    monkeypatch.setattr(calc, "BASE_CURRENCY", "NOK")
    return path


def run(path, sql, params=()):
    conn = sqlite3.connect(path)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def add_instrument(path, iid, symbol, currency="NOK", **meta):
    run(path, "INSERT INTO instruments (id, isin, symbol, name, currency, sector, region, country, asset_class) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (iid, f"ISIN{iid}", symbol, meta.get("name", symbol), currency,
         meta.get("sector"), meta.get("region"), meta.get("country"), meta.get("asset_class")))


def add_txn(path, date, type_, amount_local, instrument_id=None, quantity=None, currency="NOK"):
    run(path, "INSERT INTO transactions (account_id, instrument_id, date, type, quantity, amount, currency, amount_local) "
              "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        (instrument_id, date, type_, quantity, amount_local, currency, amount_local))


def add_price(path, iid, date, close):
    run(path, "INSERT INTO market_prices (instrument_id, date, close) VALUES (?, ?, ?)", (iid, date, close))


def add_fx(path, frm, date, rate):
    run(path, "INSERT INTO exchange_rates (from_currency, to_currency, date, rate) VALUES (?, 'NOK', ?, ?)",
        (frm, date, rate))


# ---------------------------------------------------------------------------
# get_valued_holdings
# ---------------------------------------------------------------------------
class TestValuedHoldings:

    def test_empty_database_returns_empty_frame_with_columns(self, temp_db):
        df = calc.get_valued_holdings()
        assert df.empty
        assert list(df.columns) == calc.VALUED_HOLDINGS_COLUMNS

    def test_values_priced_holding_in_base_currency(self, temp_db):
        add_instrument(temp_db, 1, "AAA", currency="USD", sector="Tech")
        add_txn(temp_db, "2026-01-10", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_price(temp_db, 1, "2026-02-01", 12.0)
        add_price(temp_db, 1, "2026-02-05", 15.0)

        df = calc.get_valued_holdings()
        assert len(df) == 1
        row = df.iloc[0]
        assert row["symbol"] == "AAA"
        assert row["has_price"]
        assert row["price"] == 15.0
        assert row["price_date"] == "2026-02-05"
        assert row["prev_date"] == "2026-02-01"
        assert row["market_value_local"] == pytest.approx(10 * 15.0 * 10.0)   # qty x price x fx
        assert row["cost_basis_local"] == pytest.approx(1000.0)
        assert row["gain_local"] == pytest.approx(500.0)
        assert row["return_pct"] == pytest.approx(50.0)
        assert row["day_change_pct"] == pytest.approx(25.0)
        assert row["day_change_local"] == pytest.approx(10 * (15.0 - 12.0) * 10.0)
        assert row["weight_pct"] == pytest.approx(100.0)
        assert row["sector"] == "Tech"
        assert row["region"] == "Unknown"

    def test_unpriced_holding_is_carried_at_cost_and_flagged(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_instrument(temp_db, 2, "BBB")
        add_txn(temp_db, "2026-01-10", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_txn(temp_db, "2026-01-10", "BUY", -3000.0, instrument_id=2, quantity=5)
        add_price(temp_db, 1, "2026-02-05", 200.0)   # only AAA is priced

        df = calc.get_valued_holdings().set_index("symbol")
        assert not df.loc["BBB", "has_price"]
        assert df.loc["BBB", "market_value_local"] == pytest.approx(3000.0)
        assert df.loc["BBB", "gain_local"] == pytest.approx(0.0)
        assert pd.isna(df.loc["BBB", "day_change_pct"])
        assert df.loc["BBB", "day_change_local"] == 0.0
        # Both positions count toward the total and weights sum to 100
        assert df["weight_pct"].sum() == pytest.approx(100.0)
        assert df.loc["AAA", "market_value_local"] == pytest.approx(2000.0)
        assert df.loc["AAA", "weight_pct"] == pytest.approx(40.0)

    def test_sold_out_position_is_excluded(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-10", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_txn(temp_db, "2026-01-20", "SELL", 1200.0, instrument_id=1, quantity=-10)
        add_price(temp_db, 1, "2026-02-05", 200.0)
        assert calc.get_valued_holdings().empty

    def test_single_price_has_no_day_change(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-10", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_price(temp_db, 1, "2026-02-05", 200.0)
        row = calc.get_valued_holdings().iloc[0]
        assert row["has_price"]
        assert pd.isna(row["day_change_pct"])
        assert row["prev_date"] is None

    def test_sorted_by_market_value_descending(self, temp_db):
        for iid, sym, qty in ((1, "SMALL", 1), (2, "BIG", 100), (3, "MID", 10)):
            add_instrument(temp_db, iid, sym)
            add_txn(temp_db, "2026-01-10", "BUY", -qty * 10.0, instrument_id=iid, quantity=qty)
            add_price(temp_db, iid, "2026-02-05", 10.0)
        assert calc.get_valued_holdings()["symbol"].tolist() == ["BIG", "MID", "SMALL"]


# ---------------------------------------------------------------------------
# get_portfolio_value_history
# ---------------------------------------------------------------------------
class TestPortfolioValueHistory:

    def test_no_prices_returns_empty_frame(self, temp_db):
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0)
        df = calc.get_portfolio_value_history()
        assert df.empty
        assert list(df.columns) == calc.PORTFOLIO_HISTORY_COLUMNS

    def test_one_row_per_price_date_with_cash_and_deposits(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0)
        add_txn(temp_db, "2026-01-02", "BUY", -600.0, instrument_id=1, quantity=6)
        add_price(temp_db, 1, "2026-01-02", 100.0)
        add_price(temp_db, 1, "2026-01-05", 110.0)
        add_price(temp_db, 1, "2026-01-09", 90.0)

        df = calc.get_portfolio_value_history()
        assert len(df) == 3
        assert df["date"].tolist() == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-09")]
        assert df["holdings_value"].tolist() == pytest.approx([600.0, 660.0, 540.0])
        assert df["cash"].tolist() == pytest.approx([400.0, 400.0, 400.0])
        assert df["total_value"].tolist() == pytest.approx([1000.0, 1060.0, 940.0])
        assert df["net_deposits"].tolist() == pytest.approx([1000.0, 1000.0, 1000.0])

    def test_quantity_changes_between_price_dates_are_reflected(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0)
        add_txn(temp_db, "2026-01-02", "BUY", -500.0, instrument_id=1, quantity=5)
        add_txn(temp_db, "2026-01-06", "SELL", 330.0, instrument_id=1, quantity=-3)   # after 2nd price date
        add_price(temp_db, 1, "2026-01-02", 100.0)
        add_price(temp_db, 1, "2026-01-05", 110.0)
        add_price(temp_db, 1, "2026-01-09", 120.0)

        df = calc.get_portfolio_value_history().set_index("date")
        assert df.loc["2026-01-05", "holdings_value"] == pytest.approx(5 * 110.0)
        assert df.loc["2026-01-09", "holdings_value"] == pytest.approx(2 * 120.0)
        assert df.loc["2026-01-09", "cash"] == pytest.approx(1000 - 500 + 330)

    def test_foreign_instrument_uses_forward_filled_fx(self, temp_db):
        add_instrument(temp_db, 1, "USD1", currency="USD")
        add_txn(temp_db, "2026-01-01", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_price(temp_db, 1, "2026-01-02", 10.0)
        add_price(temp_db, 1, "2026-01-05", 10.0)
        add_price(temp_db, 1, "2026-01-09", 10.0)
        add_fx(temp_db, "USD", "2026-01-02", 10.0)
        add_fx(temp_db, "USD", "2026-01-09", 12.0)

        df = calc.get_portfolio_value_history()
        # 01-05 has no stored rate -> carries the 01-02 rate forward
        assert df["holdings_value"].tolist() == pytest.approx([1000.0, 1000.0, 1200.0])

    def test_currency_without_stored_rates_falls_back_to_lookup(self, temp_db):
        add_instrument(temp_db, 1, "USD1", currency="USD")
        add_txn(temp_db, "2026-01-01", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_price(temp_db, 1, "2026-01-02", 10.0)
        df = calc.get_portfolio_value_history()
        assert df["holdings_value"].iloc[0] == pytest.approx(10 * 10.0 * 10.0)   # stubbed USD rate

    def test_instrument_priced_later_is_backfilled_not_zero(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_instrument(temp_db, 2, "BBB")
        add_txn(temp_db, "2026-01-01", "BUY", -100.0, instrument_id=1, quantity=1)
        add_txn(temp_db, "2026-01-01", "BUY", -200.0, instrument_id=2, quantity=1)
        add_price(temp_db, 1, "2026-01-02", 100.0)
        add_price(temp_db, 1, "2026-01-05", 100.0)
        add_price(temp_db, 2, "2026-01-05", 250.0)   # BBB only priced from the 5th

        df = calc.get_portfolio_value_history()
        assert df["holdings_value"].tolist() == pytest.approx([350.0, 350.0])

    def test_never_priced_instrument_is_carried_at_net_invested(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_instrument(temp_db, 2, "PRIVATE")
        add_txn(temp_db, "2026-01-01", "BUY", -100.0, instrument_id=1, quantity=1)
        add_txn(temp_db, "2026-01-01", "BUY", -500.0, instrument_id=2, quantity=50)
        add_price(temp_db, 1, "2026-01-02", 100.0)

        df = calc.get_portfolio_value_history()
        assert df["holdings_value"].iloc[0] == pytest.approx(600.0)

    def test_last_point_matches_valued_holdings(self, temp_db):
        """The curve's final value must agree with the current valuation."""
        add_instrument(temp_db, 1, "AAA")
        add_instrument(temp_db, 2, "USD1", currency="USD")
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 5000.0)
        add_txn(temp_db, "2026-01-02", "BUY", -1000.0, instrument_id=1, quantity=10)
        add_txn(temp_db, "2026-01-03", "BUY", -2000.0, instrument_id=2, quantity=20)
        add_price(temp_db, 1, "2026-01-05", 120.0)
        add_price(temp_db, 2, "2026-01-05", 9.0)
        add_fx(temp_db, "USD", "2026-01-05", 10.0)

        hist = calc.get_portfolio_value_history()
        valued = calc.get_valued_holdings()
        assert hist.iloc[-1]["holdings_value"] == pytest.approx(valued["market_value_local"].sum())
        assert hist.iloc[-1]["total_value"] == pytest.approx(valued["market_value_local"].sum() + 2000.0)

    def test_timestamps_in_date_column_are_normalised(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-02 00:00:00", "BUY", -100.0, instrument_id=1, quantity=1)
        add_price(temp_db, 1, "2026-01-02", 100.0)
        df = calc.get_portfolio_value_history()
        assert df["holdings_value"].iloc[0] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
class TestHelpers:

    def test_price_history_is_chronological_with_datetime_dates(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_price(temp_db, 1, "2026-01-09", 3.0)
        add_price(temp_db, 1, "2026-01-02", 1.0)
        df = calc.get_price_history(1)
        assert df["close"].tolist() == [1.0, 3.0]
        assert df["date"].iloc[0] == pd.Timestamp("2026-01-02")

    def test_price_history_unknown_instrument(self, temp_db):
        df = calc.get_price_history(99)
        assert df.empty and list(df.columns) == ["date", "close"]

    def test_monthly_dividends_fills_empty_months(self, temp_db):
        this_month = pd.Timestamp.today().to_period("M")
        prev = (this_month - 1).to_timestamp()
        add_txn(temp_db, prev.strftime("%Y-%m-15"), "DIVIDEND", 100.0)
        add_txn(temp_db, prev.strftime("%Y-%m-20"), "DIVIDEND", 50.0)

        df = calc.get_monthly_dividends(3)
        assert len(df) == 3
        assert df["month"].iloc[-1] == this_month.to_timestamp()
        assert df["total"].tolist() == pytest.approx([0.0, 150.0, 0.0])

    def test_monthly_dividends_with_no_dividends(self, temp_db):
        df = calc.get_monthly_dividends(4)
        assert len(df) == 4
        assert df["total"].sum() == 0
