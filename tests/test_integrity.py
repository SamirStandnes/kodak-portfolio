"""Tests for the integrity audit (kodak/maintenance/audit_db.py) and the
broker-id fields the Nordnet parser now emits."""
import glob
import os
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import kodak.shared.db as db
import kodak.maintenance.audit_db as audit
from tests.test_valuation import SCHEMA, run, add_instrument, add_txn, add_price, add_fx  # noqa: F401


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "audit.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO accounts (id, name, broker, external_id) VALUES (1, 'Test', 'Broker', 'ACC1')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    monkeypatch.setattr(audit, "BASE_CURRENCY", "NOK")
    return path


def levels(findings, check):
    return [x.level for x in findings if x.check == check]


class TestAudit:

    def test_clean_ledger_has_no_errors(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0)
        add_txn(temp_db, "2026-01-02", "BUY", -500.0, instrument_id=1, quantity=5)
        add_price(temp_db, 1, pd.Timestamp.today().strftime("%Y-%m-%d"), 100.0)
        findings = audit.run_audit()
        assert audit.summarize(findings)["ERROR"] == 0

    def test_unknown_type_is_an_error(self, temp_db):
        add_txn(temp_db, "2026-01-01", "MYSTERY EVENT", 30000.0)
        assert "ERROR" in levels(audit.run_audit(), "unknown_types")

    def test_time_component_in_date_is_an_error(self, temp_db):
        add_txn(temp_db, "2026-01-01 00:00:00", "DEPOSIT", 1.0)
        assert "ERROR" in levels(audit.run_audit(), "date_format")

    def test_negative_position_is_an_error(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-02", "SELL", 500.0, instrument_id=1, quantity=-5)
        assert "ERROR" in levels(audit.run_audit(), "negative_positions")

    def test_wrong_quantity_sign_is_an_error(self, temp_db):
        add_instrument(temp_db, 1, "AAA")
        add_txn(temp_db, "2026-01-02", "BUY", -500.0, instrument_id=1, quantity=-5)
        assert "ERROR" in levels(audit.run_audit(), "quantity_sign")

    def test_duplicate_broker_id_is_an_error(self, temp_db):
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 100.0, broker_id="42", balance=100.0, settle="NOK")
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 100.0, broker_id="42", balance=200.0, settle="NOK")
        assert "ERROR" in levels(audit.run_audit(), "broker_id_duplicates")

    def test_reconciliation_passes_when_balances_follow_amounts(self, temp_db):
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0, broker_id="1", balance=1000.0, settle="NOK")
        add_txn(temp_db, "2026-01-02", "FEE", -10.0, broker_id="2", balance=990.0, settle="NOK")
        add_txn(temp_db, "2026-01-03", "WITHDRAWAL", -500.0, broker_id="3", balance=490.0, settle="NOK")
        findings = audit.run_audit()
        assert levels(findings, "reconciliation") == ["INFO"]

    def test_reconciliation_names_the_row_whose_amount_differs(self, temp_db):
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0, broker_id="1", balance=1000.0, settle="NOK")
        add_txn(temp_db, "2026-01-02", "FEE", -10.0, broker_id="2", balance=980.0, settle="NOK")   # broker took 20
        findings = audit.run_audit()
        assert "ERROR" in levels(findings, "reconciliation")
        rows = next(x for x in findings if x.check == "reconciliation_rows")
        assert "2026-01-02 FEE" in rows.examples[0] and "-10.00" in rows.examples[0]

    def test_drift_that_reverses_is_only_a_warning(self, temp_db):
        """Broker booked two legs in the opposite order: balances are off for
        one step but end up right."""
        add_txn(temp_db, "2026-01-01", "DEPOSIT", 1000.0, broker_id="1", balance=1000.0, settle="NOK")
        add_txn(temp_db, "2026-01-02", "DIVIDEND", 50.0, broker_id="2", balance=990.0, settle="NOK")
        add_txn(temp_db, "2026-01-02", "FEE", -10.0, broker_id="3", balance=1040.0, settle="NOK")
        findings = audit.run_audit()
        assert "ERROR" not in levels(findings, "reconciliation")
        assert levels(findings, "reconciliation_rows") == ["WARN"]

    def test_foreign_settlement_uses_amount_not_amount_local(self, temp_db):
        add_txn(temp_db, "2026-01-01", "CURRENCY_EXCHANGE", 8000.0, currency="USD", amount=1000.0,
                broker_id="1", balance=1000.0, settle="USD")
        add_txn(temp_db, "2026-01-02", "BUY", -4500.0, currency="USD", amount=-500.0,
                broker_id="2", balance=500.0, settle="USD")
        assert levels(audit.run_audit(), "reconciliation") == ["INFO"]

    def test_missing_fx_for_held_currency_is_an_error(self, temp_db):
        add_instrument(temp_db, 1, "USD1", currency="USD")
        add_txn(temp_db, "2026-01-02", "BUY", -500.0, instrument_id=1, quantity=5, currency="USD", amount=-50.0)
        run(temp_db, "UPDATE transactions SET exchange_rate = 10")
        assert "ERROR" in levels(audit.run_audit(), "fx_coverage")


ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "new_raw_transactions" / "archive" / "nordnet"
_files = sorted(glob.glob(str(ARCHIVE / "*.csv")))


@pytest.mark.skipif(not _files, reason="needs an archived Nordnet export (gitignored)")
def test_nordnet_parser_emits_broker_id_and_balance():
    from kodak.pipeline.parsers import nordnet
    rows = nordnet.parse(_files[-1])
    assert rows, "parser returned nothing"
    ids = [r["broker_id"] for r in rows]
    assert all(i and i.isdigit() for i in ids)
    assert len(set(ids)) == len(ids), "Nordnet Ids must be unique within a file"
    assert all(isinstance(r["balance_after"], float) for r in rows)
    assert all(len(r["balance_currency"]) == 3 for r in rows)
