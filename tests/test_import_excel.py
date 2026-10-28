"""import-excel through the pipeline (ported from HES test_import_excel)."""
from expense_tracker.domain import Status
from expense_tracker.importers.excel import parse_workbook
from expense_tracker.pipeline import ingest

from tests.conftest import FIXTURES

FIXTURE = str(FIXTURES / "spese_storico.xlsx")


def _import(ledger):
    return ingest(parse_workbook(FIXTURE), ledger=ledger, classifier=None,
                  status=Status.CONFERMATO, reconcile_on=False)


def test_import_writes_every_row_confirmed(ledger):
    expected = len(parse_workbook(FIXTURE))
    s = _import(ledger)
    assert s.created == expected == ledger.count()
    assert all(r["status"] == "confermato" for r in ledger.rows.values())
    # every distinct category of the two sheets reaches finance (19 shared + 11 personal)
    assert len({r["category"] for r in ledger.rows.values()}) == 30


def test_reimport_is_idempotent(ledger):
    _import(ledger)
    s = _import(ledger)
    assert s.created == 0
    assert ledger.count() == len(parse_workbook(FIXTURE))
