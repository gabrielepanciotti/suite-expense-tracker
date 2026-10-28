# tests/test_bank_xlsx.py
from __future__ import annotations

import os
from pathlib import Path

import pytest
from expense_tracker.domain import Kind, Source
from expense_tracker.importers.bank_xlsx import parse_bbva
from expense_tracker.importers.parsing import parse_bbva_amount

FIXTURE = Path(__file__).parent / "fixtures" / "bank_bbva.xlsx"


@pytest.fixture(scope="module")
def txs():
    # The sanitized fixture uses fictional counterparty names; the importer
    # matches them via the same env vars used (untracked) on a real device.
    os.environ["BANK_SELF_NAMES"] = "alex sample"
    os.environ["BANK_MEMBER_B_NAMES"] = "blake sample"
    try:
        return parse_bbva(FIXTURE)
    finally:
        os.environ.pop("BANK_SELF_NAMES", None)
        os.environ.pop("BANK_MEMBER_B_NAMES", None)


def _find(txs, pred):
    return [t for t in txs if pred(t)]


@pytest.mark.parametrize(
    "raw, cents",
    [
        ("-66.6 EUR", -6660),   # 1 decimale → NON 666,00 (bug ×10 del parser generico)
        ("-86.4 EUR", -8640),
        ("-19.5 EUR", -1950),
        ("-53.4 EUR", -5340),
        ("-16.83 EUR", -1683),  # 2 decimali
        ("85.99 EUR", 8599),
        ("-100 EUR", -10000),   # intero
        ("2435 EUR", 243500),
        ("1.12 EUR", 112),
        ("-300 EUR", -30000),
    ],
)
def test_parse_bbva_amount_decimals(raw, cents):
    assert parse_bbva_amount(raw) == cents


def test_d161_one_decimal_not_inflated(txs):
    # cella "-66.6 EUR" → 66,60 € (era erroneamente 666,00 col parser generico)
    hits = _find(txs, lambda t: "D161 Trevi" in t.description)
    assert hits
    assert hits[0].amount_cents == 6660


def test_returns_170_all_banca(txs):
    assert len(txs) == 170
    assert all(t.source is Source.BANCA for t in txs)


def test_card_row_unicoop(txs):
    # row 11: "UNICOOP ETRURIA SC", PAGAMENTO CON CARTA, -16.83 EUR
    hits = _find(txs, lambda t: "UNICOOP" in t.description)
    assert hits, "expected a UNICOOP card row"
    t = hits[0]
    assert t.kind is Kind.SPESA_PERSONALE
    assert t.amount_cents == 1683  # abs, positive magnitude
    assert t.shared is None


def test_stipendio(txs):
    # row 9: ACCREDITO DELLO STIPENDIO / ACME S R L / 2435 EUR
    hits = _find(txs, lambda t: t.category == "STIPENDIO" and t.amount_cents == 243500)
    assert hits
    t = hits[0]
    assert t.kind is Kind.ENTRATA
    assert "ACME" in t.description
    assert t.description.startswith("Stipendio ")


def test_interessi(txs):
    hits = _find(txs, lambda t: t.category == "INTERESSI E COMPETENZE")
    assert hits
    t = hits[0]
    assert t.kind is Kind.ENTRATA
    assert t.description == "Interessi/competenze bancarie"


def test_paypal_addebito(txs):
    # row 10: ADDEBITO PayPal ... -50 EUR
    hits = _find(txs, lambda t: t.description == "PayPal (da dettagliare)")
    assert hits
    t = hits[0]
    assert t.kind is Kind.SPESA_PERSONALE
    assert t.amount_cents == 5000  # abs of -50
    assert t.shared is None


def test_scalable_addebito_investimento(txs):
    # row 75: ADDEBITO Scalable Capital Bank GmbH / -255 EUR
    hits = _find(txs, lambda t: t.category == "PAC Scalable" and t.amount_cents == 25500)
    assert hits
    t = hits[0]
    assert t.kind is Kind.INVESTIMENTO
    assert t.description == "Scalable Capital (PAC)"


def test_member_b_transfer(txs):
    # row 57: PER MICIA / member-B counterparty / -100 EUR
    hits = _find(txs, lambda t: "PER MICIA" in t.description)
    assert hits
    t = hits[0]
    assert t.kind is Kind.MEMBER_TRANSFER
    assert t.amount_cents == -10000  # signed, kept as-is
    assert "Member B" in t.description


def test_giroconto_revolut_inflow(txs):
    # row 38: Inviato da Revolut / +1000 EUR
    hits = _find(txs, lambda t: t.kind is Kind.GIROCONTO and t.amount_cents == 100000)
    assert hits
    t = hits[0]
    assert t.category == "GIROCONTO"
    assert "Revolut" in t.description


def test_giroconto_self_send_outflow(txs):
    # row 152: Trasferimento su altro conto / -810 EUR
    hits = _find(txs, lambda t: t.kind is Kind.GIROCONTO and t.amount_cents == -81000)
    assert hits
    t = hits[0]
    assert t.category == "GIROCONTO"


def test_giroconto_scalable_movimento(txs):
    # row 105: BONIFICO RICEVUTO / "Scalable Capital Deposito..." / +578.38 EUR
    hits = _find(txs, lambda t: t.kind is Kind.GIROCONTO and t.amount_cents == 57838)
    assert hits


def test_giroconto_bonifico_to_self(txs):
    # rows 24/86/151: BONIFICO ESEGUITO / benef == account holder (self)
    hits = _find(txs, lambda t: t.kind is Kind.GIROCONTO and t.amount_cents == -15000)
    assert hits


def test_third_party_bonifico_outflow(txs):
    # row 118: Visita osteopata / Stefano Boldrini / -100 EUR
    hits = _find(txs, lambda t: "osteopata" in t.description.lower())
    assert hits
    t = hits[0]
    assert t.kind is Kind.SPESA_PERSONALE
    assert t.amount_cents == 10000  # abs
    assert t.shared is None


def test_no_status_set(txs):
    # importer returns provisional rows; no status attribute is set here
    # (RawTransaction has no status field) — just sanity that kinds are populated
    assert all(t.kind is not None for t in txs)
