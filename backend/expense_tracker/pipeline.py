"""The capture chain, wired: importer -> classifier -> reconciler -> writer.

Each step is a separate component (see the sibling modules); this module only
composes them. Every entry point takes `dry_run`: the ledger is still READ
(to reconcile and dedupe) but never written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from expense_tracker import reconcile
from expense_tracker.classify import Classifier
from expense_tracker.domain import Expense, Kind, Source, Status
from expense_tracker.importers.paypal_csv import _UNRESOLVED
from expense_tracker.ledger import LedgerClient, Row
from expense_tracker.writer import to_payload


@dataclass
class ImportSummary:
    parsed: int = 0
    created: int = 0
    existing: int = 0
    reconciled: int = 0
    already_reconciled: int = 0
    per_kind: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False
    reconciled_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parsed": self.parsed, "created": self.created, "existing": self.existing,
            "reconciled": self.reconciled, "already_reconciled": self.already_reconciled,
            "per_kind": dict(sorted(self.per_kind.items())), "dry_run": self.dry_run,
            "reconciled_ids": self.reconciled_ids,
        }


def _existing_hashes(ledger: LedgerClient, expenses: list[Expense]) -> set[str]:
    """raw_hashes already in finance for the import's date span (dry-run only)."""
    dates = [e.date for e in expenses if e.date is not None]
    if not dates:
        return set()
    rows = ledger.list(date_from=min(dates).isoformat(), date_to=max(dates).isoformat())
    return {r["raw_hash"] for r in rows if r.get("raw_hash")}


def ingest(
    expenses: list[Expense],
    *,
    ledger: LedgerClient,
    classifier: Classifier | None,
    status: Status = Status.PROPOSTO,
    reconcile_on: bool = True,
    dry_run: bool = False,
) -> ImportSummary:
    """Push captured expenses to finance, reconciling bank lines with pending receipts."""
    summary = ImportSummary(parsed=len(expenses), dry_run=dry_run)
    if classifier is not None:
        expenses = [classifier.classify(e) for e in expenses]

    pending: list[Row] = []
    if reconcile_on:
        span = reconcile.window(expenses)
        if span is not None:
            # Whole window, every page: a truncated read would hide candidates silently.
            pending = ledger.list(date_from=span[0].isoformat(), date_to=span[1].isoformat())
    known = _existing_hashes(ledger, expenses) if dry_run else set()

    for e in expenses:
        decision = reconcile.decide(e, pending) if reconcile_on else None
        if decision is not None and decision.outcome is reconcile.Outcome.ALREADY:
            summary.already_reconciled += 1
            continue
        if decision is not None and decision.outcome is reconcile.Outcome.EXISTS:
            summary.existing += 1
            continue
        if decision is not None and decision.outcome is reconcile.Outcome.MATCHED:
            assert decision.txn_id is not None and decision.changes is not None
            if not dry_run:
                ledger.patch(decision.txn_id, decision.changes)
            # Keep the local view in sync so the same receipt is not matched twice.
            for row in pending:
                if row["id"] == decision.txn_id:
                    row.update(decision.changes)
            summary.reconciled += 1
            summary.reconciled_ids.append(decision.txn_id)
            continue

        kind = e.kind.value if e.kind else "?"
        if dry_run:
            created = e.raw_hash not in known
            known.add(e.raw_hash)
        else:
            _, created = ledger.create(to_payload(e, status))
        if created:
            summary.created += 1
            summary.per_kind[kind] = summary.per_kind.get(kind, 0) + 1
        else:
            summary.existing += 1
    return summary


def register_expense(
    e: Expense,
    *,
    ledger: LedgerClient,
    classifier: Classifier | None = None,
    status: Status = Status.PROPOSTO,
    dry_run: bool = False,
) -> tuple[Row, bool]:
    """Register ONE expense (default `proposto`, awaiting the bank line).

    This is what Health does for a supplement or a visit: the purchase exists
    before the statement. When the bank line arrives, `ingest` confirms it.
    Explicit fields win over the learned classification.
    """
    if classifier is not None:
        learned = classifier.classify(e)
        e.category = e.category or learned.category
        e.kind = e.kind or learned.kind
        e.shared = e.shared if e.shared is not None else learned.shared
    payload = to_payload(e, status)
    if dry_run:
        return payload, True
    return ledger.create(payload)


# --- PayPal ------------------------------------------------------------------

def _date_distance(a: date | None, b: str | date | None) -> int:
    if a is None or b in (None, ""):
        return 10**9
    bd = b if isinstance(b, date) else date.fromisoformat(str(b)[:10])
    return abs((a - bd).days)


def detail_paypal(
    items: list[Expense], *, ledger: LedgerClient, dry_run: bool = False
) -> dict[str, Any]:
    """Rename opaque bank proposals `PayPal (da dettagliare)` with the real merchant.

    Ported from HES `detail_paypal`: only `description` changes, no row is
    created or deleted. Pass 1 matches exact amounts (nearest date on ties);
    pass 2 gives leftovers to the free proposal with the smallest amount delta
    (bank vs PayPal off by a fee).
    """
    proposals = [
        r for r in ledger.list(status=Status.PROPOSTO.value, source=Source.BANCA.value)
        if str(r.get("description") or "").startswith("PayPal")
    ]
    remaining = list(proposals)
    matched: list[tuple[Expense, Row]] = []
    leftover: list[Expense] = []

    for item in items:
        candidates = [p for p in remaining if p["amount_cents"] == item.amount_cents]
        if not candidates:
            leftover.append(item)
            continue
        best = min(candidates, key=lambda p: _date_distance(item.date, p.get("date")))
        remaining.remove(best)
        matched.append((item, best))

    for item in leftover:
        if not remaining:
            break
        best = min(remaining, key=lambda p: abs(p["amount_cents"] - item.amount_cents))
        remaining.remove(best)
        matched.append((item, best))

    identified = generic = 0
    for item, prop in matched:
        if not dry_run:
            ledger.patch(prop["id"], {"description": item.description})
        if item.description == _UNRESOLVED:
            generic += 1
        else:
            identified += 1
    return {
        "detailed": len(matched),
        "identified": identified,
        "generic": generic,
        "unmatched_proposals": len(remaining),
        "dry_run": dry_run,
    }


# --- review ------------------------------------------------------------------

def pending_proposals(ledger: LedgerClient) -> list[Row]:
    rows = ledger.list(status=Status.PROPOSTO.value)
    return sorted(rows, key=lambda r: (r.get("date") or "", r["id"]))


def confirm_proposal(
    row: Row,
    *,
    ledger: LedgerClient,
    classifier: Classifier,
    category: str | None,
    kind: str,
    shared: bool,
    learn_pattern: str | None = None,
    dry_run: bool = False,
) -> Row:
    """Confirm a proposal in finance and, optionally, learn the merchant.

    Raises ValueError on an unknown kind before anything is written.
    """
    kind_value = Kind(kind).value
    changes = {
        "status": Status.CONFERMATO.value,
        "category": category,
        "kind": kind_value,
        "shared": shared,
    }
    if row.get("recon_status") == "auto":
        changes["recon_status"] = "confermata"
    if dry_run:
        return {**row, **changes}
    updated = ledger.patch(row["id"], changes)
    if learn_pattern:
        classifier.learn(learn_pattern, category, kind_value, shared)
    return updated
