"""Runtime configuration (env-driven; secrets and per-device values stay in `.env`)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DATA_DIR = REPO_ROOT / "data"

load_dotenv(REPO_ROOT / ".env")

# finance node, back port from Life docs/ports.registry.json (id `finance`, back 10023).
DEFAULT_FINANCE_URL = "http://127.0.0.1:10023"


def finance_url() -> str:
    return os.environ.get("FINANCE_URL", DEFAULT_FINANCE_URL).rstrip("/")


def finance_timeout() -> float:
    return float(os.environ.get("FINANCE_TIMEOUT", "15"))


def database_url() -> str:
    """Sync SQLAlchemy URL for the node's own DB (merchant_map + import log).

    `DATABASE_URL` from the deploy compose wins; an async driver is swapped for
    psycopg (which serves both sync and async). Unset -> local SQLite under data/.
    """
    url = os.environ.get("DATABASE_URL") or os.environ.get("EXPENSETRACKER_DATABASE_URL")
    if not url:
        return f"sqlite:///{DATA_DIR / 'expensetracker.sqlite'}"
    url = url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
