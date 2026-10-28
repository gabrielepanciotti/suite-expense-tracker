"""The node's own data: `merchant_map` (learned classification) + `imports` (log).

Nothing else. Expenses live in finance; keeping a copy here would make two
ledgers that silently diverge.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from expense_tracker.classify import MerchantRule
from expense_tracker.domain import Kind
from sqlalchemy import Boolean, DateTime, Integer, String, create_engine, false, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from suite_backend_core import Base

from expense_tracker_backend.config import DATA_DIR, database_url


class MerchantMap(Base):
    __tablename__ = "merchant_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String, unique=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    hits: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ImportLog(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # bank | excel | paypal
    source_file: Mapped[str] = mapped_column(String)
    parsed: Mapped[int] = mapped_column(Integer)
    created: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reconciled: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _to_rule(m: MerchantMap) -> MerchantRule:
    return MerchantRule(
        pattern=m.pattern, category=m.category, kind=m.kind, shared=m.shared, hits=m.hits
    )


class SqlMerchantStore:
    """MerchantStore on the node's DB (same semantics as the in-memory fake)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def rules(self) -> list[MerchantRule]:
        return [_to_rule(m) for m in self.session.scalars(select(MerchantMap))]

    def learn(self, pattern: str, category: str | None, kind: str, shared: bool) -> MerchantRule:
        kind = Kind(kind).value
        row = self.session.scalar(select(MerchantMap).where(MerchantMap.pattern == pattern))
        if row is not None:
            # Re-learning updates the mapping (the user may have corrected it) and bumps hits.
            row.category, row.kind, row.shared = category, kind, shared
            row.hits += 1
        else:
            row = MerchantMap(pattern=pattern, category=category, kind=kind, shared=shared, hits=1)
            self.session.add(row)
        self.session.commit()
        return _to_rule(row)

    def log_import(
        self, *, kind: str, source_file: str, parsed: int, created: int, reconciled: int
    ) -> None:
        self.session.add(ImportLog(
            kind=kind, source_file=source_file, parsed=parsed, created=created,
            reconciled=reconciled,
        ))
        self.session.commit()


_engine: Engine | None = None


def get_engine() -> Engine:
    """Lazily built engine. SQLite (dev/tests) gets its tables created; Postgres uses Alembic."""
    global _engine
    if _engine is None:
        url = database_url()
        if url.startswith("sqlite"):
            DATA_DIR.mkdir(exist_ok=True)
        _engine = create_engine(url)
        if url.startswith("sqlite"):
            Base.metadata.create_all(_engine)
    return _engine


def ping() -> None:
    """Raise if the node database cannot accept a basic query."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


@contextmanager
def open_store(engine: Engine | None = None) -> Iterator[SqlMerchantStore]:
    session = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)()
    try:
        yield SqlMerchantStore(session)
    finally:
        session.close()
