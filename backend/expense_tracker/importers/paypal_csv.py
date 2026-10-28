"""Importer dell'estratto PayPal (CSV export).

Il portafoglio PayPal viene alimentato dalla banca con bonifici cumulativi:
nell'estratto BBVA ogni alimentazione appare come una riga opaca
``PayPal (da dettagliare)``. Questo export PayPal dettaglia COSA ha pagato
ciascuna alimentazione, così da rinominare le righe banca col merchant reale.

Formato CSV (verificato): UTF-8 con BOM (``utf-8-sig``), numeri italiani con la
virgola decimale (``-454,93``), date ``d/m/Y`` (``1/4/2026``). Le intestazioni
hanno spazi finali su ``Lordo `` e ``Tariffa `` — vanno usate così come sono.

Per ogni riga ``Descrizione == "Bonifico bancario sul conto PayPal"`` (positiva)
si produce UNA ``Expense`` (una spesa, magnitudine positiva). Il merchant
si risolve seguendo la catena dei ``Codice transazione di riferimento`` fino a
una riga con ``Nome`` di un merchant reale (che NON contiene ``PayPal (Europe)``).
Le catene che terminano su un ``Pagamento generico`` senza nome/ref restano non
identificabili in questo export.

Tutte le righe sono provvisorie: il chiamante non assegna alcuno status.
"""
from __future__ import annotations

import csv
from pathlib import Path

from expense_tracker.domain import Expense, Kind, Payer, Source
from expense_tracker.importers.parsing import parse_amount_cents, parse_date

_BONIFICO_DESC = "Bonifico bancario sul conto PayPal"
_PAYPAL_INTERNAL = "PayPal (Europe)"
_UNRESOLVED = "PayPal generico (da identificare)"
_MAX_DEPTH = 6


def _resolve_merchant(code: str, by_code: dict[str, dict], depth: int = 0) -> str | None:
    """Segue la catena dei riferimenti fino a un merchant reale.

    Ritorna il ``Nome`` della prima riga che NON è una riga interna PayPal, o
    ``None`` se la catena si esaurisce / supera la profondità massima / cicla.
    """
    r = by_code.get(code)
    if r is None or depth > _MAX_DEPTH:
        return None
    nome = r["Nome"].strip()
    if nome and _PAYPAL_INTERNAL not in nome:
        return nome
    ref2 = r["Codice transazione di riferimento"].strip()
    if ref2 and ref2 != code:
        return _resolve_merchant(ref2, by_code, depth + 1)
    return None


def parse_paypal(path: str | Path) -> list[Expense]:
    """Legge l'estratto PayPal → una Expense per ogni bonifico bancario."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    by_code = {row["Codice transazione"].strip(): row for row in rows}

    out: list[Expense] = []
    for row in rows:
        if row["Descrizione"].strip() != _BONIFICO_DESC:
            continue
        ref = row["Codice transazione di riferimento"].strip()
        merchant = _resolve_merchant(ref, by_code) if ref else None
        out.append(Expense(
            date=parse_date(row["Data"]),
            description=merchant or _UNRESOLVED,
            amount_cents=abs(parse_amount_cents(row["Lordo "])),
            source=Source.PAYPAL,
            kind=Kind.SPESA_PERSONALE,
            shared=None,
            category=None,
            payer=Payer.MEMBER_A,
        ))

    # Indice di occorrenza fra righe altrimenti identiche (dedup-safe), come parse_bbva.
    seen: dict[tuple, int] = {}
    for t in out:
        key = (t.date, t.description, t.amount_cents)
        t.seq = seen.get(key, 0)
        seen[key] = t.seq + 1
    return out
