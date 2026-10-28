"""PayPal CSV importer + detail_paypal (ported from HES, detail now PATCHes finance)."""
from __future__ import annotations

from datetime import date

from expense_tracker.domain import Expense, Kind, Source
from expense_tracker.importers.paypal_csv import parse_paypal
from expense_tracker.ledger import FakeLedgerClient
from expense_tracker.pipeline import detail_paypal
from expense_tracker.writer import to_payload

from tests.conftest import FIXTURES

FIXTURE = str(FIXTURES / "paypal_sample.csv")


# --- parse_paypal (unchanged from HES) ----------------------------------------

def _by_amount(items: list[Expense]) -> dict[int, Expense]:
    return {i.amount_cents: i for i in items}


def test_parse_paypal_one_item_per_bonifico():
    items = parse_paypal(FIXTURE)
    assert len(items) == 5
    assert all(i.source is Source.PAYPAL for i in items)
    assert all(i.kind is Kind.SPESA_PERSONALE for i in items)
    assert all(i.amount_cents > 0 for i in items)


def test_parse_paypal_direct_merchant():
    item = _by_amount(parse_paypal(FIXTURE))[12000]
    assert item.description == "KoRo Handels GmbH"
    assert item.date == date(2026, 4, 1)


def test_parse_paypal_chained_merchant():
    assert _by_amount(parse_paypal(FIXTURE))[8532].description == "Ryanair Limited"


def test_parse_paypal_dead_end_is_unresolved():
    item = _by_amount(parse_paypal(FIXTURE))[7522]
    assert item.description == "PayPal generico (da identificare)"


def test_parse_paypal_same_amount_distinct_dates():
    items = [i for i in parse_paypal(FIXTURE) if i.amount_cents == 3387]
    assert len(items) == 2
    assert {i.date for i in items} == {date(2026, 4, 7), date(2026, 4, 9)}
    assert {i.description for i in items} == {"Amazon EU", "Spotify AB"}


# --- detail_paypal against a fake finance --------------------------------------

def _seed_bank_proposal(ledger: FakeLedgerClient, d: date, amount_cents: int) -> int:
    e = Expense(date=d, description="PayPal (da dettagliare)", amount_cents=amount_cents,
                source=Source.BANCA, kind=Kind.SPESA_PERSONALE)
    row, _ = ledger.create(to_payload(e))
    return row["id"]


def test_detail_paypal_rewrites_descriptions(ledger):
    _seed_bank_proposal(ledger, date(2026, 4, 1), 12000)
    _seed_bank_proposal(ledger, date(2026, 4, 3), 8532)
    _seed_bank_proposal(ledger, date(2026, 4, 5), 7522)

    summary = detail_paypal(parse_paypal(FIXTURE), ledger=ledger)

    descs = {r["description"] for r in ledger.rows.values()}
    assert {"KoRo Handels GmbH", "Ryanair Limited", "PayPal generico (da identificare)"} <= descs
    assert summary["unmatched_proposals"] == 0
    assert summary["identified"] == 2
    assert summary["generic"] == 1


def test_detail_paypal_dup_amount_matches_nearest_date(ledger):
    amz = _seed_bank_proposal(ledger, date(2026, 4, 7), 3387)
    spot = _seed_bank_proposal(ledger, date(2026, 4, 9), 3387)
    detail_paypal(parse_paypal(FIXTURE), ledger=ledger)
    assert ledger.rows[amz]["description"] == "Amazon EU"
    assert ledger.rows[spot]["description"] == "Spotify AB"


def test_detail_paypal_off_by_fee_matches_in_pass2(ledger):
    prop = _seed_bank_proposal(ledger, date(2026, 4, 1), 11990)
    summary = detail_paypal(parse_paypal(FIXTURE), ledger=ledger)
    assert ledger.rows[prop]["description"] == "KoRo Handels GmbH"
    assert summary["unmatched_proposals"] == 0


def test_detail_paypal_only_touches_description(ledger):
    prop = _seed_bank_proposal(ledger, date(2026, 4, 1), 12000)
    detail_paypal(parse_paypal(FIXTURE), ledger=ledger)
    patches = [c for c in ledger.calls if c[0] == "patch"]
    assert patches == [("patch", (prop, {"description": "KoRo Handels GmbH"}))]
    row = ledger.rows[prop]
    assert row["amount_cents"] == 12000
    assert row["status"] == "proposto"
    assert row["kind"] == Kind.SPESA_PERSONALE.value


def test_detail_paypal_ignores_confirmed_rows(ledger):
    confirmed = _seed_bank_proposal(ledger, date(2026, 4, 1), 12000)
    ledger.patch(confirmed, {"status": "confermato"})
    ledger.calls.clear()
    summary = detail_paypal(parse_paypal(FIXTURE), ledger=ledger)
    assert summary["detailed"] == 0
    assert ledger.writes() == []


def test_detail_paypal_dry_run_writes_nothing(ledger):
    _seed_bank_proposal(ledger, date(2026, 4, 1), 12000)
    ledger.calls.clear()
    summary = detail_paypal(parse_paypal(FIXTURE), ledger=ledger, dry_run=True)
    assert summary["detailed"] == 1 and summary["dry_run"] is True
    assert ledger.writes() == []
