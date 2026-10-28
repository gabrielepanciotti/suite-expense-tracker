"""The ledger is the `finance` node. expenseTracker only talks to it through this Protocol.

Contract (finance HTTP API): rows are plain dicts with at least `id`, `date`
(ISO string or None), `description`, `amount_cents`, `source`, `category`,
`kind`, `shared`, `payer`, `status`, `raw_hash`, `buoni_cents`,
`recon_status`, `recon_source`, `tags`.

`FakeLedgerClient` is the in-memory stand-in used by every test: it mirrors
the contract (idempotent create on `raw_hash`, filters, PATCH) so the pipeline
is exercised without a network.
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Any, Protocol

Row = dict[str, Any]

# Filters understood by finance `GET /api/transactions`.
LIST_FILTERS = (
    "date_from", "date_to", "tag", "category", "kind", "shared", "status", "source", "payer",
)


class LedgerError(RuntimeError):
    """finance refused or could not be reached. Never swallowed into an empty result."""


class LedgerClient(Protocol):
    def create(self, payload: Row) -> tuple[Row, bool]:
        """POST a transaction. Returns (row, created) — created=False when raw_hash existed."""
        ...

    def list(self, **filters: Any) -> list[Row]:
        """All rows matching the filters (pagination handled by the client)."""
        ...

    def get(self, txn_id: int) -> Row: ...

    def patch(self, txn_id: int, changes: Row) -> Row: ...


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class FakeLedgerClient:
    """In-memory finance. Records every call for assertions."""

    _MUTABLE = {
        "date", "description", "amount_cents", "source", "category", "kind", "shared",
        "payer", "status", "note", "payment_method", "buoni_cents", "recon_status",
        "recon_source", "member_b_share_bp", "tags",
    }

    def __init__(self, rows: list[Row] | None = None) -> None:
        self.rows: dict[int, Row] = {}
        self.calls: list[tuple[str, Any]] = []
        self._next_id = 1
        for r in rows or []:
            self._insert(dict(r))

    def _insert(self, payload: Row) -> Row:
        row: Row = {
            "date": None, "category": None, "kind": None, "shared": None,
            "payer": "member_a", "status": "confermato", "raw_hash": None, "note": None,
            "payment_method": None, "buoni_cents": 0, "recon_status": "nessuna",
            "recon_source": None, "member_b_share_bp": None, "tags": [],
        }
        row.update(payload)
        row["id"] = payload.get("id") or self._next_id
        self._next_id = max(self._next_id, row["id"]) + 1
        if isinstance(row.get("date"), date):
            row["date"] = row["date"].isoformat()
        self.rows[row["id"]] = row
        return row

    def create(self, payload: Row) -> tuple[Row, bool]:
        self.calls.append(("create", payload))
        h = payload.get("raw_hash")
        if h:
            for row in self.rows.values():
                if row.get("raw_hash") == h:
                    return copy.deepcopy(row), False
        return copy.deepcopy(self._insert(dict(payload))), True

    def list(self, **filters: Any) -> list[Row]:
        self.calls.append(("list", filters))
        unknown = set(filters) - set(LIST_FILTERS) - {"limit", "offset"}
        if unknown:
            raise LedgerError(f"unsupported filters: {sorted(unknown)}")
        d_from = _as_date(filters.get("date_from"))
        d_to = _as_date(filters.get("date_to"))
        out = []
        for row in sorted(self.rows.values(), key=lambda r: (r.get("date") or "", r["id"])):
            d = _as_date(row.get("date"))
            if d_from and (d is None or d < d_from):
                continue
            if d_to and (d is None or d > d_to):
                continue
            skip = False
            for key in ("category", "kind", "shared", "status", "source", "payer"):
                if key in filters and filters[key] is not None and row.get(key) != filters[key]:
                    skip = True
            if "tag" in filters and filters["tag"] not in (row.get("tags") or []):
                skip = True
            if not skip:
                out.append(copy.deepcopy(row))
        return out

    def get(self, txn_id: int) -> Row:
        if txn_id not in self.rows:
            raise LedgerError(f"transaction {txn_id} not found")
        return copy.deepcopy(self.rows[txn_id])

    def patch(self, txn_id: int, changes: Row) -> Row:
        self.calls.append(("patch", (txn_id, changes)))
        if txn_id not in self.rows:
            raise LedgerError(f"transaction {txn_id} not found")
        bad = set(changes) - self._MUTABLE
        if bad:
            raise LedgerError(f"immutable fields: {sorted(bad)}")
        self.rows[txn_id].update(copy.deepcopy(changes))
        return copy.deepcopy(self.rows[txn_id])

    # --- test helpers -------------------------------------------------------
    def count(self) -> int:
        return len(self.rows)

    def writes(self) -> list[tuple[str, Any]]:
        return [c for c in self.calls if c[0] in ("create", "patch")]
