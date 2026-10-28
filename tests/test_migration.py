"""Alembic 0001 renders for Postgres (offline) and matches the ORM tables."""
import io
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def test_migration_0001_renders_offline(monkeypatch):
    monkeypatch.chdir(BACKEND)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/expensetracker")
    buf = io.StringIO()
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=buf)
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE merchant_map" in sql
    assert "CREATE TABLE imports" in sql
    assert "transactions" not in sql  # expenses live in finance, never here


def test_orm_tables_match_migration():
    import expense_tracker_backend.db  # noqa: F401
    from suite_backend_core import Base

    assert {"merchant_map", "imports"} <= set(Base.metadata.tables)
    cols = set(Base.metadata.tables["merchant_map"].columns.keys())
    assert cols == {"id", "pattern", "category", "kind", "shared", "hits"}
