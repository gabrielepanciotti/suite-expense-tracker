from pathlib import Path

import expense_tracker_backend.db  # noqa: F401  (registers the node tables on Base)
import pytest
from expense_tracker.classify import Classifier, InMemoryMerchantStore
from expense_tracker.ledger import FakeLedgerClient
from expense_tracker_backend.db import SqlMerchantStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from suite_backend_core import Base

FIXTURES = Path(__file__).parent / "fixtures"

# Device-local env (from the untracked .env) must never leak into tests.
_DEVICE_LOCAL_VARS = [
    "BANK_SELF_NAMES",
    "BANK_MEMBER_B_NAMES",
    "LEGACY_SHARED_SHEET",
    "LEGACY_PERSONAL_SHEET",
    "FINANCE_URL",
    "DATABASE_URL",
    "EXPENSETRACKER_DATABASE_URL",
]


@pytest.fixture(autouse=True)
def _neutral_device_env(monkeypatch):
    for var in _DEVICE_LOCAL_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def ledger() -> FakeLedgerClient:
    return FakeLedgerClient()


@pytest.fixture()
def store() -> InMemoryMerchantStore:
    return InMemoryMerchantStore()


@pytest.fixture()
def classifier(store) -> Classifier:
    return Classifier(store)


@pytest.fixture()
def sql_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def sql_store(sql_engine):
    session = sessionmaker(bind=sql_engine, expire_on_commit=False)()
    try:
        yield SqlMerchantStore(session)
    finally:
        session.close()
