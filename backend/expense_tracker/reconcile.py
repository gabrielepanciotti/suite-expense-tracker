"""Reconciler: is this bank line the same expense as a receipt already in finance?

Ported from HomeExpenseSplitter `reconcile.py` and cut in two:

- HERE: "these two rows are the same expense" -> the receipt goes
  `proposto -> confermato` with `recon_status='auto'`, `recon_source=<bank raw_hash>`,
  and no duplicate row is created.
- NOT HERE: `rimborsato` (member B paid back). That is the splitter's job and
  this module never reads nor writes it.

The decision is a pure function over the rows finance returned for the date
window (`decide`), so it is testable without any ledger at all.

Differences from HES, on purpose:
- a candidate is any `proposto` row not coming from a bank document (HES only
  looked at `source='manuale'`): Health registers purchases the same way;
- kind must be an expense kind on both sides, not the *same* kind: the bank
  line is classified by merchant, the receipt by the person who knew it was
  shared — requiring equality made a shared receipt never match;
- `recon_source` stores the bank line's raw_hash, and a bank line whose hash is
  already some row's `recon_source` is recognised as reconciled: in HES a
  re-import of the same statement created the duplicate the match had avoided.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from expense_tracker.domain import BANK_SOURCES, EXPENSE_KINDS, Expense, ReconStatus, Status
from expense_tracker.ledger import Row

WINDOW_DAYS = 4


class Outcome(StrEnum):
    NEW = "new"  # nothing to reconcile: write the bank line as its own row
    MATCHED = "matched"  # one receipt found: PATCH it instead of creating
    ALREADY = "already"  # this bank line already reconciled a receipt earlier
    EXISTS = "exists"  # this bank line is already its own row in finance: leave it to review


@dataclass(slots=True)
class Decision:
    outcome: Outcome
    txn_id: int | None = None
    changes: Row | None = None


def _row_date(row: Row) -> date | None:
    d = row.get("date")
    if d is None or d == "":
        return None
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def is_reconcilable(e: Expense) -> bool:
    """Only a dated bank-side expense can be the bank line of a receipt."""
    return (
        e.date is not None
        and e.source in BANK_SOURCES
        and (e.kind is None or e.kind in EXPENSE_KINDS)
        and e.amount_cents > 0
    )


def is_candidate(row: Row, e: Expense, window_days: int = WINDOW_DAYS) -> bool:
    d = _row_date(row)
    if d is None or e.date is None or abs((d - e.date).days) > window_days:
        return False
    if row.get("status") != Status.PROPOSTO.value:
        return False
    if (row.get("recon_status") or ReconStatus.NESSUNA.value) != ReconStatus.NESSUNA.value:
        return False
    if row.get("source") in {s.value for s in BANK_SOURCES}:
        return False
    if row.get("kind") is not None and row.get("kind") not in {k.value for k in EXPENSE_KINDS}:
        return False
    card = int(row.get("amount_cents") or 0) - int(row.get("buoni_cents") or 0)
    return card == e.amount_cents


def decide(e: Expense, rows: list[Row], window_days: int = WINDOW_DAYS) -> Decision:
    """High-confidence match only: exactly one candidate, otherwise leave it to review."""
    if not is_reconcilable(e):
        return Decision(Outcome.NEW)
    h = e.raw_hash
    for row in rows:
        if row.get("recon_source") == h:
            return Decision(Outcome.ALREADY, txn_id=row["id"])
        if row.get("raw_hash") == h:
            # Written on an earlier import, before its receipt existed. Confirming the
            # receipt now would leave two rows for one expense; review decides instead.
            return Decision(Outcome.EXISTS, txn_id=row["id"])
    candidates = [r for r in rows if is_candidate(r, e, window_days)]
    if len(candidates) != 1:
        return Decision(Outcome.NEW)
    receipt = candidates[0]
    return Decision(
        Outcome.MATCHED,
        txn_id=receipt["id"],
        changes={
            "description": f"{receipt.get('description') or ''} | {e.description}".strip(" |"),
            "status": Status.CONFERMATO.value,
            "recon_status": ReconStatus.AUTO.value,
            "recon_source": h,
        },
    )


def window(expenses: list[Expense], window_days: int = WINDOW_DAYS) -> tuple[date, date] | None:
    """Date span covering every reconcilable expense ± the window (one GET for a whole import)."""
    dates = [e.date for e in expenses if is_reconcilable(e) and e.date is not None]
    if not dates:
        return None
    pad = timedelta(days=window_days)
    return min(dates) - pad, max(dates) + pad
