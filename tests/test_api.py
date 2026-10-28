"""FastAPI app with the ledger and the store overridden by fakes."""
import pytest
from expense_tracker.classify import InMemoryMerchantStore
from expense_tracker.ledger import FakeLedgerClient, LedgerError
from expense_tracker_backend import db
from expense_tracker_backend.app import app, get_ledger, get_store
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from tests.conftest import FIXTURES


@pytest.fixture()
def fakes():
    ledger, store = FakeLedgerClient(), InMemoryMerchantStore()
    app.dependency_overrides[get_ledger] = lambda: ledger
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield ledger, store
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client(fakes):
    return TestClient(app)


def test_health(client, monkeypatch):
    memory = create_engine("sqlite://")
    monkeypatch.setattr(db, "get_engine", lambda: memory)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "expense-tracker"
    assert response.json()["database"] == "ok"


def test_health_is_unavailable_when_database_is_down(client, monkeypatch):
    def unavailable():
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(db, "get_engine", unavailable)
    assert client.get("/health").status_code == 503


def test_register_expense_proposto_forwarded(client, fakes):
    ledger, _ = fakes
    body = {"date": "2026-03-02", "description": "Visita", "amount_cents": 8000,
            "kind": "spesa_personale", "tags": ["health"]}
    r = client.post("/api/expenses", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["created"] is True
    assert out["transaction"]["status"] == "proposto"
    assert out["transaction"]["raw_hash"]
    assert ledger.count() == 1
    again = client.post("/api/expenses", json=body)
    assert again.status_code == 200 and again.json()["created"] is False


def test_register_expense_validates(client):
    r = client.post("/api/expenses", json={"date": "2026-03-02", "description": "",
                                           "amount_cents": 1})
    assert r.status_code == 422
    r = client.post("/api/expenses", json={"date": "2026-03-02", "description": "x",
                                           "amount_cents": 1, "status": "rimborsato"})
    assert r.status_code == 422


def test_import_bank_upload(client, fakes):
    ledger, store = fakes
    with open(FIXTURES / "bank_bbva.xlsx", "rb") as fh:
        r = client.post("/api/import/bank", files={"file": ("estratto.xlsx", fh)})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 170 and ledger.count() == 170
    assert store.imports[0]["kind"] == "bank"


def test_import_dry_run_writes_nothing(client, fakes):
    ledger, store = fakes
    with open(FIXTURES / "bank_bbva.xlsx", "rb") as fh:
        r = client.post("/api/import/bank?dry_run=true", files={"file": ("e.xlsx", fh)})
    assert r.json()["dry_run"] is True and ledger.count() == 0 and store.imports == []


def test_import_paypal_upload(client, fakes):
    with open(FIXTURES / "paypal_sample.csv", "rb") as fh:
        r = client.post("/api/import/paypal", files={"file": ("pp.csv", fh)})
    assert r.status_code == 200 and r.json()["detailed"] == 0


def test_import_bank_pdf_upload(client, fakes):
    ledger, store = fakes
    with open(FIXTURES / "bank_bbva.pdf", "rb") as fh:
        r = client.post("/api/import/bank_pdf", files={"file": ("estratto.pdf", fh)})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 5 and ledger.count() == 5
    assert store.imports[0]["kind"] == "bank_pdf"


def test_import_receipt_upload(client, fakes):
    from expense_tracker_backend.app import get_ocr

    class FakeOcr:
        def extract_text(self, path):
            return "COOP CENTRO ITALIA\nTOTALE 3,70\n"

    ledger, _ = fakes
    app.dependency_overrides[get_ocr] = lambda: FakeOcr()
    try:
        r = client.post("/api/import/receipt", files={"file": ("scontrino.jpg", b"img")})
    finally:
        app.dependency_overrides.pop(get_ocr, None)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] is True
    assert out["transaction"]["source"] == "scontrino"
    assert out["transaction"]["status"] == "proposto"
    assert ledger.count() == 1


def test_import_receipt_unreadable_is_422(client, fakes):
    from expense_tracker_backend.app import get_ocr

    class BadOcr:
        def extract_text(self, path):
            raise ValueError("importo non trovato nello scontrino")

    app.dependency_overrides[get_ocr] = lambda: BadOcr()
    try:
        r = client.post("/api/import/receipt", files={"file": ("scontrino.jpg", b"img")})
    finally:
        app.dependency_overrides.pop(get_ocr, None)
    assert r.status_code == 422


def test_import_unreadable_document_is_422(client):
    r = client.post("/api/import/bank", files={"file": ("x.xlsx", b"not an xlsx")})
    assert r.status_code == 422


def test_unknown_import_kind_is_422(client):
    r = client.post("/api/import/pdf", files={"file": ("x.pdf", b"x")})
    assert r.status_code == 422


def test_finance_down_is_502(client, fakes):
    class Down(FakeLedgerClient):
        def create(self, payload):
            raise LedgerError("finance unreachable")

    app.dependency_overrides[get_ledger] = lambda: Down()
    r = client.post("/api/expenses", json={"date": "2026-03-02", "description": "x",
                                           "amount_cents": 1})
    assert r.status_code == 502


def test_merchant_map(client, fakes):
    _, store = fakes
    store.learn("UNICOOP", "SUPERMERCATO", "spesa_condivisa", True)
    r = client.get("/api/merchant-map")
    assert r.json() == [{"pattern": "UNICOOP", "category": "SUPERMERCATO",
                         "kind": "spesa_condivisa", "shared": True, "hits": 1}]
