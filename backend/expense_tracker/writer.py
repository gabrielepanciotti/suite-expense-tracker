"""Writer: Expense -> finance `POST /api/transactions` payload.

Always carries `raw_hash`, so finance can answer "already there" (200) on a
re-import instead of creating a second copy.
"""
from __future__ import annotations

from expense_tracker.domain import Expense, Status
from expense_tracker.ledger import Row


def to_payload(e: Expense, status: Status = Status.PROPOSTO) -> Row:
    payload: Row = {
        "date": e.date.isoformat() if e.date else None,
        "description": e.description,
        "amount_cents": e.amount_cents,
        "source": e.source.value,
        "category": e.category,
        "kind": e.kind.value if e.kind else None,
        "shared": e.shared,
        "payer": e.payer.value,
        "status": Status(status).value,
        "raw_hash": e.raw_hash,
        "note": e.note,
        "payment_method": e.payment_method,
        "buoni_cents": e.buoni_cents or None,
        "member_b_share_bp": e.member_b_share_bp,
        "tags": list(e.tags) or None,
    }
    # Unset fields are omitted rather than sent as null: finance applies its own defaults.
    return {k: v for k, v in payload.items() if v is not None}
