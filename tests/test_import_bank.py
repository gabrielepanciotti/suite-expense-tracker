"""import-bank through the pipeline (ported from HES test_import_bank, finance faked)."""
from __future__ import annotations

import pytest
from expense_tracker.domain import Kind
from expense_tracker.importers.bank_xlsx import parse_bbva
from expense_tracker.pipeline import confirm_proposal, ingest, pending_proposals

from tests.conftest import FIXTURES

FIXTURE = str(FIXTURES / "bank_bbva.xlsx")


def _import(ledger, classifier, **kw):
    return ingest(parse_bbva(FIXTURE), ledger=ledger, classifier=classifier, **kw)


def test_import_bank_inserts_proposals(ledger, classifier):
    s = _import(ledger, classifier)
    assert s.parsed == 170 and s.created == 170
    assert ledger.count() == 170
    assert all(r["status"] == "proposto" for r in ledger.rows.values())
    assert all(r["raw_hash"] for r in ledger.rows.values())


def test_import_bank_is_idempotent(ledger, classifier):
    _import(ledger, classifier)
    s = _import(ledger, classifier)
    assert s.parsed == 170 and s.created == 0 and s.existing == 170
    assert ledger.count() == 170


def test_import_bank_applies_learned_merchant(ledger, classifier):
    classifier.learn("UNICOOP ETRURIA", "SUPERMERCATO", "spesa_condivisa", True)
    _import(ledger, classifier)
    rows = [r for r in ledger.rows.values() if "UNICOOP" in r["description"]]
    assert rows
    assert rows[0]["category"] == "SUPERMERCATO"
    assert rows[0]["kind"] == Kind.SPESA_CONDIVISA.value
    assert rows[0]["shared"] is True


def test_import_bank_no_classify_leaves_provisional(ledger, classifier):
    classifier.learn("UNICOOP ETRURIA", "SUPERMERCATO", "spesa_condivisa", True)
    _import(ledger, None)
    rows = [r for r in ledger.rows.values() if "UNICOOP" in r["description"]]
    assert rows and rows[0].get("category") is None


def test_import_bank_dry_run_writes_nothing(ledger, classifier):
    s = _import(ledger, classifier, dry_run=True)
    assert s.created == 170 and s.dry_run
    assert ledger.count() == 0 and ledger.writes() == []


def test_import_bank_dry_run_after_import_reports_existing(ledger, classifier):
    _import(ledger, classifier)
    s = _import(ledger, classifier, dry_run=True)
    assert s.created == 0 and s.existing == 170


def test_parse_bbva_assigns_seq_to_duplicates():
    assert any(t.seq > 0 for t in parse_bbva(FIXTURE))


def test_parse_bbva_seq_is_stable():
    assert [t.seq for t in parse_bbva(FIXTURE)] == [t.seq for t in parse_bbva(FIXTURE)]


# --- review (pending_proposals / confirm_proposal) -----------------------------

def test_pending_proposals_only_proposto_sorted(ledger, classifier):
    _import(ledger, classifier)
    first = pending_proposals(ledger)[0]
    confirm_proposal(first, ledger=ledger, classifier=classifier, category="X",
                     kind="spesa_personale", shared=False)
    pending = pending_proposals(ledger)
    assert all(r["status"] == "proposto" for r in pending)
    dates = [r["date"] for r in pending if r["date"]]
    assert dates == sorted(dates)
    assert first["id"] not in {r["id"] for r in pending}


def test_confirm_proposal_and_learn(ledger, classifier, store):
    _import(ledger, classifier)
    txn = pending_proposals(ledger)[0]
    out = confirm_proposal(txn, ledger=ledger, classifier=classifier, category="SUPERMERCATO",
                           kind="spesa_condivisa", shared=True, learn_pattern=txn["description"])
    assert out["status"] == "confermato"
    assert (out["category"], out["kind"], out["shared"]) == (
        "SUPERMERCATO", "spesa_condivisa", True)
    assert [r.pattern for r in store.rules()] == [txn["description"]]


def test_confirm_proposal_invalid_kind_raises_before_writing(ledger, classifier):
    _import(ledger, classifier)
    txn = pending_proposals(ledger)[0]
    ledger.calls.clear()
    with pytest.raises(ValueError):
        confirm_proposal(txn, ledger=ledger, classifier=classifier, category="X",
                         kind="non_esiste", shared=False)
    assert ledger.writes() == []


def test_confirm_proposal_dry_run(ledger, classifier, store):
    _import(ledger, classifier)
    txn = pending_proposals(ledger)[0]
    ledger.calls.clear()
    confirm_proposal(txn, ledger=ledger, classifier=classifier, category="X",
                     kind="spesa_personale", shared=False, learn_pattern="X", dry_run=True)
    assert ledger.writes() == [] and list(store.rules()) == []
