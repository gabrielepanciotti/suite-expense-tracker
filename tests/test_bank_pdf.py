# tests/test_bank_pdf.py
"""Estratto conto banca PDF → [Expense] (source=BANCA), testo e file reale."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from expense_tracker.domain import Kind, Source
from expense_tracker.importers.bank_pdf import parse_bank_pdf, parse_bank_pdf_text

FIXTURE = Path(__file__).parent / "fixtures" / "bank_bbva.pdf"

SAMPLE = (
    "Data contabile  Operazione  Descrizione  Importo\n"
    "02/03/2026  Pagamento con carta  UNICOOP ETRURIA SC  -16,83\n"
    "03/03/2026  ACCREDITO DELLO STIPENDIO  ACME S R L  2435 EUR\n"
    "04/03/2026  ADDEBITO PayPal  -50,00\n"
    "05/03/2026  Inviato da Revolut  1000 EUR\n"
    "06/03/2026  LIQUIDAZIONE INTERESSI  0,12\n"
    "Saldo finale  3368,29\n"
)


def _by_desc(txs, needle):
    return [t for t in txs if needle in t.description]


def test_ignores_header_footer_and_counts():
    txs = parse_bank_pdf_text(SAMPLE)
    assert len(txs) == 5
    assert all(t.source is Source.BANCA for t in txs)


def test_card_row_positive_magnitude():
    t = _by_desc(parse_bank_pdf_text(SAMPLE), "UNICOOP")[0]
    assert t.kind is Kind.SPESA_PERSONALE
    assert t.amount_cents == 1683  # abs of -16,83
    assert t.date == date(2026, 3, 2)


def test_stipendio_entrata():
    t = _by_desc(parse_bank_pdf_text(SAMPLE), "STIPENDIO")[0]
    assert t.kind is Kind.ENTRATA
    assert t.category == "STIPENDIO"
    assert t.amount_cents == 243500


def test_paypal_opaque_proposal():
    t = _by_desc(parse_bank_pdf_text(SAMPLE), "PayPal")[0]
    assert t.description == "PayPal (da dettagliare)"
    assert t.kind is Kind.SPESA_PERSONALE
    assert t.amount_cents == 5000


def test_giroconto_keeps_sign():
    t = _by_desc(parse_bank_pdf_text(SAMPLE), "Revolut")[0]
    assert t.kind is Kind.GIROCONTO
    assert t.amount_cents == 100000  # signed inflow, kept as-is


def test_interessi_entrata():
    t = _by_desc(parse_bank_pdf_text(SAMPLE), "Interessi")[0]
    assert t.kind is Kind.ENTRATA
    assert t.category == "INTERESSI E COMPETENZE"
    assert t.amount_cents == 12


def test_parse_bank_pdf_from_real_file():
    txs = parse_bank_pdf(FIXTURE)
    assert len(txs) == 5
    assert all(t.kind is not None for t in txs)
    assert sum(1 for t in txs if t.amount_cents > 0 and t.kind is Kind.SPESA_PERSONALE) >= 2


def test_assigns_seq_for_duplicates():
    dup = (
        "01/01/2026  Pagamento con carta  NEGOZIO  -10,00\n"
        "01/01/2026  Pagamento con carta  NEGOZIO  -10,00\n"
    )
    txs = parse_bank_pdf_text(dup)
    assert [t.seq for t in txs] == [0, 1]
