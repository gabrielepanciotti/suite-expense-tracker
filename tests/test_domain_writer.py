"""raw_hash parity with HomeExpenseSplitter, payload shape, single-expense registration."""
from datetime import date

from expense_tracker.classify import Classifier
from expense_tracker.domain import Expense, Kind, Source, Status
from expense_tracker.importers.bank_xlsx import parse_bbva
from expense_tracker.pipeline import ingest, register_expense
from expense_tracker.writer import to_payload

from tests.conftest import FIXTURES

# Golden value produced by HES `store.repo.raw_hash` on the first fixture row
# (verified 2026-09-21 on all 170 bank + 316 excel rows: identical hashes).
HES_FIRST_BANK_ROW_HASH = "6c83cf41ebea3a8d35bcbbf120a48708a873d246209d59ee4a2a87396100e965"


def test_raw_hash_is_byte_identical_to_hes():
    first = parse_bbva(FIXTURES / "bank_bbva.xlsx")[0]
    assert (first.date, first.amount_cents, first.source, first.seq) == (
        date(2026, 6, 13), 595, Source.BANCA, 0)
    assert first.raw_hash == HES_FIRST_BANK_ROW_HASH


def test_raw_hash_ignores_kind_and_shared_but_not_seq():
    a = Expense(date=date(2026, 1, 1), description="X", amount_cents=100, source=Source.BANCA)
    b = Expense(date=date(2026, 1, 1), description=" x ", amount_cents=100, source=Source.BANCA,
                kind=Kind.SPESA_CONDIVISA, shared=True)
    c = Expense(date=date(2026, 1, 1), description="X", amount_cents=100, source=Source.BANCA,
                seq=1)
    assert a.raw_hash == b.raw_hash != c.raw_hash


def test_payload_always_carries_raw_hash_and_omits_unset():
    e = Expense(date=date(2026, 2, 3), description="Farmacia", amount_cents=1250,
                source=Source.MANUALE, shared=False, tags=["salute"], member_b_share_bp=3300)
    p = to_payload(e)
    assert p["raw_hash"] == e.raw_hash
    assert p["status"] == "proposto"
    assert p["date"] == "2026-02-03"
    assert p["shared"] is False  # False is a value, not "unset"
    assert p["tags"] == ["salute"] and p["member_b_share_bp"] == 3300
    assert "category" not in p and "kind" not in p and "buoni_cents" not in p
    assert to_payload(e, Status.CONFERMATO)["status"] == "confermato"


def test_status_has_no_rimborsato():
    assert {s.value for s in Status} == {"proposto", "confermato"}


def test_register_proposto_then_bank_confirms_it(ledger):
    """The Health case: a purchase registered before the statement, confirmed by it."""
    purchase = Expense(date=date(2026, 3, 2), description="Integratore magnesio",
                       amount_cents=1890, source=Source.MANUALE, kind=Kind.SPESA_CONDIVISA,
                       shared=True, member_b_share_bp=3333, tags=["health"])
    row, created = register_expense(purchase, ledger=ledger)
    assert created and row["status"] == "proposto" and row["member_b_share_bp"] == 3333

    bank = Expense(date=date(2026, 3, 4), description="FARMACIA CENTRALE", amount_cents=1890,
                   source=Source.BANCA, kind=Kind.SPESA_PERSONALE)
    s = ingest([bank], ledger=ledger, classifier=None)
    assert s.reconciled == 1 and ledger.count() == 1
    final = ledger.rows[row["id"]]
    assert final["status"] == "confermato" and final["recon_status"] == "auto"
    assert final["shared"] is True and final["member_b_share_bp"] == 3333


def test_register_is_idempotent_and_explicit_fields_win(ledger, classifier):
    classifier.learn("FARMACIA", "SALUTE", "spesa_personale", False)
    e = Expense(date=date(2026, 3, 2), description="Farmacia", amount_cents=500,
                source=Source.MANUALE, shared=True)
    row, created = register_expense(e, ledger=ledger, classifier=classifier)
    assert created
    assert (row["category"], row["kind"], row["shared"]) == ("SALUTE", "spesa_personale", True)
    _, again = register_expense(e, ledger=ledger, classifier=classifier)
    assert again is False and ledger.count() == 1


def test_register_dry_run_writes_nothing(ledger):
    e = Expense(date=date(2026, 3, 2), description="X", amount_cents=500, source=Source.MANUALE)
    payload, created = register_expense(e, ledger=ledger, dry_run=True)
    assert created and payload["raw_hash"] == e.raw_hash and ledger.count() == 0


def test_classifier_used_by_ingest(ledger, store):
    store.learn("HO-MOBILE", "TELEFONO", "spesa_personale", False)
    s = ingest(parse_bbva(FIXTURES / "bank_bbva.xlsx")[:1], ledger=ledger,
               classifier=Classifier(store))
    assert s.created == 1
    assert next(iter(ledger.rows.values()))["category"] == "TELEFONO"
