"""Importer dell'estratto conto banca in PDF (BBVA).

A differenza di `bank_xlsx` (che legge le celle di un foglio), qui il PDF è già
un flusso di testo: una riga = una riga di estratto. Si estrae il testo con
pypdf e ogni riga viene riconosciuta dal pattern ``data … descrizione … importo``
(importo in coda, con segno). Le righe senza data o senza importo (intestazione,
saldi, note) sono ignorate.

La classificazione è un sottoinsieme deliberato di quella del xlsx — le parole
chiave più utili (stipendio, interessi, PayPal, PAC, giroconto, member transfer),
poi fallback sul segno. Il `merchant_map` e la `review` affinano il resto: qui
non si duplica l'intera tabella di regole del foglio.

Convenzione segno identica a `bank_xlsx`: spese/entrate/investimenti a magnitudine
positiva, member_transfer/giroconto signed. Source sempre `BANCA`: la riga PDF è
una riga di banca come quella dell'xlsx, non un documento a parte.
"""
from __future__ import annotations

import re
from pathlib import Path

from expense_tracker.domain import Expense, Kind, Payer, Source
from expense_tracker.importers.parsing import (
    collapse_ws,
    env_names,
    parse_bbva_amount,
    parse_date,
)
from expense_tracker.ocr import extract_pdf_text

# `data  <body>  importo` — l'importo è l'ultimo token (eventuale EUR/€ in coda).
_ROW_RE = re.compile(
    r"^\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<body>.+?)\s+"
    r"(?P<amount>[+-]?\d[\d.,]*)\s*(?:EUR|€)?\s*$"
)

# Parole che segnalano un giroconto fra conti propri anche in assenza di env names.
_GIROCONTO_HINTS = ("revolut", "scalable", "trasferimento", "instant transfer", "giroconto")


def _classify_pdf(desc: str, amount: int) -> dict:
    """Inferisce description/kind/category dal testo della riga (prima corrispondenza vince)."""
    abs_amount = abs(amount)
    desc_cf = desc.casefold()

    if "paypal" in desc_cf:
        return dict(description="PayPal (da dettagliare)", amount_cents=abs_amount,
                    kind=Kind.SPESA_PERSONALE, category=None)
    if "scalable capital" in desc_cf:
        return dict(description="Scalable Capital (PAC)", amount_cents=abs_amount,
                    kind=Kind.INVESTIMENTO, category="PAC Scalable")
    if "accredito dello stipendio" in desc_cf:
        return dict(description=desc, amount_cents=abs_amount,
                    kind=Kind.ENTRATA, category="STIPENDIO")
    if "liquidazione interessi" in desc_cf:
        return dict(description="Interessi/competenze bancarie", amount_cents=abs_amount,
                    kind=Kind.ENTRATA, category="INTERESSI E COMPETENZE")

    # Trasferimento da/verso l'altro membro della casa (counterparty in env).
    if any(name in desc_cf for name in env_names("BANK_MEMBER_B_NAMES")):
        return dict(description=f"{desc} — Member B", amount_cents=amount,
                    kind=Kind.MEMBER_TRANSFER, category=None)

    # Giroconto fra conti propri: hint testuali o counterparty = account holder.
    if any(h in desc_cf for h in _GIROCONTO_HINTS) or any(
        name in desc_cf for name in env_names("BANK_SELF_NAMES")
    ):
        return dict(description=desc, amount_cents=amount,
                    kind=Kind.GIROCONTO, category="GIROCONTO")

    kind = Kind.SPESA_PERSONALE if amount < 0 else Kind.ENTRATA
    return dict(description=desc, amount_cents=abs_amount, kind=kind, category=None)


def parse_bank_pdf_text(text: str) -> list[Expense]:
    """Testo estratto dal PDF → lista di Expense provvisorie (source=BANCA)."""
    out: list[Expense] = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m is None:
            continue
        try:
            amount = parse_bbva_amount(m.group("amount"))
        except ValueError:
            continue
        d = parse_date(m.group("date"))
        desc = collapse_ws(m.group("body"))
        if not desc:
            continue
        fields = _classify_pdf(desc, amount)
        out.append(Expense(
            date=d, source=Source.BANCA, payer=Payer.MEMBER_A, shared=None,
            description=collapse_ws(fields["description"]),
            amount_cents=fields["amount_cents"],
            kind=fields["kind"], category=fields["category"],
        ))

    seen: dict[tuple, int] = {}
    for t in out:
        key = (t.date, t.description, t.amount_cents)
        t.seq = seen.get(key, 0)
        seen[key] = t.seq + 1
    return out


def parse_bank_pdf(path: str | Path) -> list[Expense]:
    """Legge l'estratto conto banca PDF → lista di Expense provvisorie."""
    return parse_bank_pdf_text(extract_pdf_text(path))
