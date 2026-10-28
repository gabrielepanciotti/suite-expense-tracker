"""Typer CLI with finance and the store replaced by fakes."""
from contextlib import contextmanager

import pytest
from expense_tracker.classify import InMemoryMerchantStore
from expense_tracker.ledger import FakeLedgerClient
from expense_tracker_backend import cli
from typer.testing import CliRunner

from tests.conftest import FIXTURES

runner = CliRunner()


@pytest.fixture()
def fakes(monkeypatch):
    ledger, store = FakeLedgerClient(), InMemoryMerchantStore()

    @contextmanager
    def _store():
        yield store

    monkeypatch.setattr(cli, "make_ledger", lambda: ledger)
    monkeypatch.setattr(cli, "store_ctx", _store)
    return ledger, store


def test_import_bank_and_reimport(fakes):
    ledger, store = fakes
    r = runner.invoke(cli.app, ["import-bank", str(FIXTURES / "bank_bbva.xlsx")])
    assert r.exit_code == 0, r.output
    assert "170 nuove" in r.output and ledger.count() == 170
    assert store.imports and store.imports[0]["source_file"] == "bank_bbva.xlsx"
    r = runner.invoke(cli.app, ["import-bank", str(FIXTURES / "bank_bbva.xlsx")])
    assert "0 nuove, 170 già in finance" in r.output


def test_import_bank_dry_run(fakes):
    ledger, store = fakes
    r = runner.invoke(cli.app, ["import-bank", str(FIXTURES / "bank_bbva.xlsx"), "--dry-run"])
    assert r.exit_code == 0 and r.output.startswith("[dry-run]")
    assert ledger.count() == 0 and store.imports == []


def test_import_excel_confirmed(fakes):
    ledger, _ = fakes
    r = runner.invoke(cli.app, ["import-excel", str(FIXTURES / "spese_storico.xlsx")])
    assert r.exit_code == 0, r.output
    assert ledger.count() > 0
    assert {row["status"] for row in ledger.rows.values()} == {"confermato"}


def test_import_paypal(fakes):
    ledger, _ = fakes
    ledger.create({"date": "2026-04-01", "description": "PayPal (da dettagliare)",
                   "amount_cents": 12000, "source": "banca", "status": "proposto",
                   "raw_hash": "h1"})
    r = runner.invoke(cli.app, ["import-paypal", str(FIXTURES / "paypal_sample.csv")])
    assert r.exit_code == 0, r.output
    assert "1 proposte dettagliate" in r.output
    assert next(iter(ledger.rows.values()))["description"] == "KoRo Handels GmbH"


def test_import_bank_pdf(fakes):
    ledger, store = fakes
    r = runner.invoke(cli.app, ["import-bank-pdf", str(FIXTURES / "bank_bbva.pdf")])
    assert r.exit_code == 0, r.output
    assert "5 nuove" in r.output and ledger.count() == 5
    assert store.imports[0]["kind"] == "bank_pdf"


def test_import_receipt(monkeypatch, fakes):
    ledger, _ = fakes

    class FakeOcr:
        def extract_text(self, path):
            return "COOP CENTRO ITALIA\nTOTALE 3,70\n"

    monkeypatch.setattr(cli, "make_ocr", lambda: FakeOcr())
    r = runner.invoke(cli.app, ["import-receipt", "scontrino.jpg"])
    assert r.exit_code == 0, r.output
    row = next(iter(ledger.rows.values()))
    assert row["source"] == "scontrino" and row["status"] == "proposto"
    assert row["amount_cents"] == 370 and row["description"] == "COOP CENTRO ITALIA"


def test_import_receipt_unreadable_exits_nonzero(monkeypatch, fakes):
    ledger, _ = fakes

    class BadOcr:
        def extract_text(self, path):
            raise ValueError("importo non trovato nello scontrino")

    monkeypatch.setattr(cli, "make_ocr", lambda: BadOcr())
    r = runner.invoke(cli.app, ["import-receipt", "scontrino.jpg"])
    assert r.exit_code == 1 and ledger.count() == 0


def test_add_registers_proposto(fakes):
    ledger, _ = fakes
    r = runner.invoke(cli.app, ["add", "--desc", "EUROSPAR", "--amount", "50,00",
                                "--date", "10/01/2026", "--buoni", "16",
                                "--kind", "spesa_condivisa", "--shared"])
    assert r.exit_code == 0, r.output
    row = next(iter(ledger.rows.values()))
    assert row["status"] == "proposto" and row["buoni_cents"] == 1600
    assert row["amount_cents"] == 5000


def test_add_dry_run_and_bad_date(fakes):
    ledger, _ = fakes
    r = runner.invoke(cli.app, ["add", "--desc", "X", "--amount", "1", "--date", "10/01/2026",
                                "--dry-run"])
    assert r.exit_code == 0 and ledger.count() == 0
    r = runner.invoke(cli.app, ["add", "--desc", "X", "--amount", "1", "--date", "ieri"])
    assert r.exit_code != 0


def test_review_confirms_and_learns(fakes):
    ledger, store = fakes
    ledger.create({"date": "2026-01-10", "description": "UNICOOP ETRURIA", "amount_cents": 1683,
                   "source": "banca", "status": "proposto", "kind": "spesa_personale",
                   "raw_hash": "h"})
    # c=correct -> kind, category, shared?, learn? pattern
    answers = "c\nspesa_condivisa\nSUPERMERCATO\ny\ny\nUNICOOP\n"
    r = runner.invoke(cli.app, ["review"], input=answers)
    assert r.exit_code == 0, r.output
    row = next(iter(ledger.rows.values()))
    assert (row["status"], row["kind"], row["category"], row["shared"]) == (
        "confermato", "spesa_condivisa", "SUPERMERCATO", True)
    assert [x.pattern for x in store.rules()] == ["UNICOOP"]


def test_review_dry_run_writes_nothing(fakes):
    ledger, store = fakes
    ledger.create({"date": "2026-01-10", "description": "X", "amount_cents": 1,
                   "source": "banca", "status": "proposto", "kind": "spesa_personale",
                   "raw_hash": "h"})
    ledger.calls.clear()
    r = runner.invoke(cli.app, ["review", "--dry-run"], input="\ny\nX\n")
    assert r.exit_code == 0, r.output
    assert ledger.writes() == [] and list(store.rules()) == []


def test_finance_down_exits_nonzero(monkeypatch, fakes):
    from expense_tracker.ledger import LedgerError

    class Down(FakeLedgerClient):
        def list(self, **f):
            raise LedgerError("finance unreachable")

    monkeypatch.setattr(cli, "make_ledger", lambda: Down())
    r = runner.invoke(cli.app, ["review"])
    assert r.exit_code == 1
