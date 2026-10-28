# tests/test_receipt.py
"""Scontrino (foto/PDF) → una Expense `proposto` non-banca, OCR dietro un finto."""
from __future__ import annotations

from datetime import date

import pytest
from expense_tracker.domain import Source
from expense_tracker.importers.receipt import parse_receipt, parse_receipt_text


class FakeOcr:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self, path) -> str:
        return self.text


SAMPLE = (
    "COOP CENTRO ITALIA\n"
    "Via Roma 1\n"
    "Data: 03/03/2026 14:32\n"
    "BISCOTTI       2,50\n"
    "LATTE          1,20\n"
    "TOTALE         3,70\n"
)


def test_total_from_totale_line():
    assert parse_receipt_text(SAMPLE).amount_cents == 370


def test_date_parsed():
    assert parse_receipt_text(SAMPLE).date == date(2026, 3, 3)


def test_merchant_is_first_non_noise_line():
    assert parse_receipt_text(SAMPLE).description == "COOP CENTRO ITALIA"


def test_source_is_scontrino_unclassified():
    e = parse_receipt_text(SAMPLE)
    assert e.source is Source.SCONTRINO
    assert (e.kind, e.category, e.shared) == (None, None, None)


def test_total_fallback_to_largest_money_line():
    text = "MARKET\n03/03/2026\npane 1,00\nvino 5,50\n"
    e = parse_receipt_text(text)
    assert e.amount_cents == 550
    assert e.description == "MARKET"


def test_noise_title_skipped_for_merchant():
    text = "SCONTRINO\nCOOP CENTRO ITALIA\nTOTALE 3,70\n"
    assert parse_receipt_text(text).description == "COOP CENTRO ITALIA"


def test_missing_amount_raises():
    with pytest.raises(ValueError):
        parse_receipt_text("solo testo senza importi")


def test_empty_raises():
    with pytest.raises(ValueError):
        parse_receipt_text("")


def test_parse_receipt_delegates_to_ocr():
    e = parse_receipt("scontrino.jpg", FakeOcr(SAMPLE))
    assert e.amount_cents == 370
    assert e.date == date(2026, 3, 3)
    assert e.source is Source.SCONTRINO
