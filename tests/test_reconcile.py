"""Reconciler: receipt <-> bank line (ported from HES test_reconcile + test_import_bank_reconcile).

`rimborsato` does not exist here: reconciliation only moves proposto -> confermato.
"""
from datetime import date

from expense_tracker import reconcile
from expense_tracker.domain import Expense, Kind, Source, Status
from expense_tracker.pipeline import ingest, register_expense

_seq = 0


def _receipt(ledger, amount, buoni, d=date(2026, 1, 10), kind=Kind.SPESA_CONDIVISA,
             source=Source.MANUALE):
    global _seq
    _seq += 1
    e = Expense(date=d, description=f"EUROSPAR scontrino #{_seq}", amount_cents=amount,
                source=source, kind=kind, category="SUPERMERCATO", shared=True,
                payment_method="misto", buoni_cents=buoni)
    row, _ = register_expense(e, ledger=ledger)
    return row["id"]


def _bank(amount, d=date(2026, 1, 12), desc="PAGOBANCOMAT EUROSPAR", kind=Kind.SPESA_PERSONALE):
    return Expense(date=d, description=desc, amount_cents=amount, source=Source.BANCA, kind=kind)


def test_exact_match_considers_buoni(ledger):
    rid = _receipt(ledger, 5000, 1600)  # card = 34,00
    d = reconcile.decide(_bank(3400), ledger.list())
    assert d.outcome is reconcile.Outcome.MATCHED and d.txn_id == rid


def test_no_candidate_returns_new(ledger):
    _receipt(ledger, 5000, 1600)
    assert reconcile.decide(_bank(9999), ledger.list()).outcome is reconcile.Outcome.NEW


def test_ambiguous_two_candidates_returns_new(ledger):
    _receipt(ledger, 3400, 0)
    _receipt(ledger, 3400, 0)
    out = reconcile.decide(_bank(3400, d=date(2026, 1, 11)), ledger.list())
    assert out.outcome is reconcile.Outcome.NEW


def test_out_of_window_returns_new(ledger):
    _receipt(ledger, 3400, 0, d=date(2026, 1, 1))
    out = reconcile.decide(_bank(3400, d=date(2026, 1, 20)), ledger.list())
    assert out.outcome is reconcile.Outcome.NEW


def test_window_edges_are_inclusive(ledger):
    _receipt(ledger, 3400, 0, d=date(2026, 1, 8))
    out = reconcile.decide(_bank(3400, d=date(2026, 1, 12)), ledger.list())
    assert out.outcome is reconcile.Outcome.MATCHED


def test_match_changes_confirm_and_mark_recon(ledger):
    _receipt(ledger, 5000, 1600)
    bank = _bank(3400)
    d = reconcile.decide(bank, ledger.list())
    assert d.changes["status"] == Status.CONFERMATO.value
    assert d.changes["recon_status"] == "auto"
    assert d.changes["recon_source"] == bank.raw_hash
    assert "PAGOBANCOMAT EUROSPAR" in d.changes["description"]
    assert "rimborsato" not in str(d.changes)


def test_shared_receipt_matches_unclassified_personal_bank_line(ledger):
    # HES required the SAME kind: a shared receipt never met a spesa_personale bank line.
    _receipt(ledger, 3400, 0, kind=Kind.SPESA_CONDIVISA)
    d = reconcile.decide(_bank(3400, kind=Kind.SPESA_PERSONALE), ledger.list())
    assert d.outcome is reconcile.Outcome.MATCHED


def test_bank_rows_and_confirmed_rows_are_not_candidates(ledger):
    other_bank = _bank(3400, desc="ALTRA RIGA BANCA")
    ledger.create({"description": other_bank.description, "amount_cents": 3400,
                   "date": "2026-01-11", "source": "banca", "status": "proposto",
                   "raw_hash": other_bank.raw_hash, "kind": "spesa_personale"})
    rid = _receipt(ledger, 3400, 0)
    ledger.patch(rid, {"status": "confermato"})
    assert reconcile.decide(_bank(3400), ledger.list()).outcome is reconcile.Outcome.NEW


def test_income_is_never_reconciled(ledger):
    _receipt(ledger, 3400, 0)
    income = _bank(3400, kind=Kind.ENTRATA)
    assert reconcile.decide(income, ledger.list()).outcome is reconcile.Outcome.NEW


def test_non_manual_capture_source_is_a_candidate(ledger):
    # Any non-bank source awaiting the bank qualifies (HES only looked at 'manuale').
    _receipt(ledger, 2500, 0, source=Source.SCREENSHOT, kind=Kind.SPESA_PERSONALE)
    assert reconcile.decide(_bank(2500), ledger.list()).outcome is reconcile.Outcome.MATCHED


def test_pure_decide_needs_no_ledger():
    rows = [{"id": 7, "date": "2026-01-10", "status": "proposto", "source": "manuale",
             "kind": "spesa_personale", "amount_cents": 1200, "buoni_cents": 0,
             "recon_status": "nessuna", "description": "farmacia"}]
    assert reconcile.decide(_bank(1200), rows).txn_id == 7


# --- through the pipeline (HES test_import_bank_reconcile) --------------------

def test_bank_line_enriches_existing_receipt_no_duplicate(ledger):
    rid = _receipt(ledger, 5000, 1600)
    s = ingest([_bank(3400)], ledger=ledger, classifier=None)
    assert ledger.count() == 1
    assert s.reconciled == 1 and s.created == 0 and s.reconciled_ids == [rid]
    row = ledger.rows[rid]
    assert row["recon_status"] == "auto" and row["status"] == "confermato"


def test_bank_line_without_match_inserts(ledger):
    s = ingest([_bank(3400)], ledger=ledger, classifier=None)
    assert ledger.count() == 1 and s.created == 1
    assert next(iter(ledger.rows.values()))["status"] == "proposto"


def test_reimport_after_reconcile_creates_no_duplicate(ledger):
    # HES bug: the second import found no candidate and inserted the bank line.
    _receipt(ledger, 5000, 1600)
    ingest([_bank(3400)], ledger=ledger, classifier=None)
    s = ingest([_bank(3400)], ledger=ledger, classifier=None)
    assert ledger.count() == 1
    assert s.already_reconciled == 1 and s.created == 0


def test_bank_line_already_in_finance_does_not_confirm_a_late_receipt(ledger):
    ingest([_bank(3400)], ledger=ledger, classifier=None)  # statement first
    _receipt(ledger, 3400, 0)  # receipt registered later
    s = ingest([_bank(3400)], ledger=ledger, classifier=None)
    assert s.existing == 1 and s.reconciled == 0
    assert ledger.count() == 2
    assert all(r["status"] == "proposto" for r in ledger.rows.values())


def test_one_receipt_is_matched_once_within_an_import(ledger):
    _receipt(ledger, 3400, 0)
    s = ingest([_bank(3400, desc="RIGA A"), _bank(3400, desc="RIGA B")],
               ledger=ledger, classifier=None)
    assert s.reconciled == 1 and s.created == 1


def test_dry_run_reconcile_writes_nothing(ledger):
    _receipt(ledger, 5000, 1600)
    ledger.calls.clear()
    s = ingest([_bank(3400)], ledger=ledger, classifier=None, dry_run=True)
    assert s.reconciled == 1 and ledger.writes() == []
