"""Importer di uno scontrino (foto o PDF) → UNA `Expense` `proposto` non-banca.

Il testo arriva da un `OcrEngine` (Tesseract per le foto, pypdf per i PDF);
`parse_receipt_text` è la funzione pura che dal testo ricava data, totale e
merchant — testabile senza alcun motore OCR, con un finto che restituisce testo.

Lo scontrino è la "riga non-banca" che il reconciler aggancerà alla riga di
banca quando arriva: nasce `proposto`, `source=scontrino`, senza kind/category
(li propone il `merchant_map`, altrimenti la `review`). Nessuno status viene
assegnato qui: è compito del chiamante.

Euristica (deliberatamente conservativa, documentata):
- **totale**: l'ultima riga che contiene "totale"/"total"; altrimenti il più
  grande importo fra le righe che sembrano soldi (hanno €/EUR o 2 decimali);
- **data**: la prima occorrenza `gg/mm/aaaa` (separatori .-/ normalizzati);
- **merchant**: la prima riga non-data, non-importo, non-rumore ("scontrino",
  "ricevuta", …). Se nulla sopravvive → descrizione "Scontrino".
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from expense_tracker.domain import Expense, Payer, Source
from expense_tracker.importers.parsing import collapse_ws, parse_amount_cents, parse_date
from expense_tracker.ocr import OcrEngine

_DATE_RE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")
_MONEY_RE = re.compile(r"[€]|EUR|\d[.,]\d{2}")
_AMOUNT_ONLY_RE = re.compile(r"^[-+]?\d[\d.,]*\s*(?:EUR|€)?$")
_TOTAL_KEYWORDS = ("totale", "total", "tot.")
_NOISE = {"scontrino", "ricevuta", "fattura", "negozio", "cassa", "documento", "spesa"}

_UNKNOWN_MERCHANT = "Scontrino"


def _find_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if m is None:
        return None
    d, mo, y = m.groups()
    return parse_date(f"{d}/{mo}/{y}")


def _find_total(lines: list[str]) -> int:
    for line in reversed(lines):
        if any(k in line.casefold() for k in _TOTAL_KEYWORDS):
            try:
                return parse_amount_cents(line)
            except ValueError:
                continue
    candidates: list[int] = []
    for line in lines:
        if not _MONEY_RE.search(line):
            continue
        try:
            candidates.append(parse_amount_cents(line))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("importo non trovato nello scontrino")
    return max(candidates)


def _find_merchant(lines: list[str]) -> str:
    for line in lines:
        s = collapse_ws(line)
        if not s:
            continue
        if _DATE_RE.search(s):
            continue  # riga data (anche "Data: 03/03/2026 14:30")
        if _AMOUNT_ONLY_RE.match(s):
            continue  # riga solo importo
        if s.casefold() in _NOISE:
            continue
        return s
    return _UNKNOWN_MERCHANT


def parse_receipt_text(text: str) -> Expense:
    """Testo dello scontrino (OCR o PDF) → una `Expense` `proposto` non classificata."""
    lines = [ln for ln in (line.strip() for line in text.splitlines()) if ln]
    if not lines:
        raise ValueError("scontrino vuoto")
    return Expense(
        date=_find_date(text),
        description=_find_merchant(lines),
        amount_cents=_find_total(lines),
        source=Source.SCONTRINO,
        kind=None,
        category=None,
        shared=None,
        payer=Payer.MEMBER_A,
    )


def parse_receipt(path: str | Path, ocr: OcrEngine) -> Expense:
    """Legge una foto/PDF di scontrino → una `Expense`."""
    return parse_receipt_text(ocr.extract_text(path))
