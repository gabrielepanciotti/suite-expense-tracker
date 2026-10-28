# ExpenseTracker

ExpenseTracker captures expenses from bank statements, legacy spreadsheets, PayPal exports, receipts, and manual entries; it suggests classifications and writes confirmed records to a compatible finance ledger API without keeping a second transaction history.

## Features

- Import BBVA XLSX/PDF statements, legacy Excel files, PayPal CSV exports, and receipt images or PDFs.
- Reconcile proposed receipts against bank transactions.
- Learn merchant-to-category mappings and expose a small FastAPI and CLI interface.
- Keep imports idempotent by sending a stable `raw_hash` to the ledger.

## Requirements

- Python 3.13
- A compatible finance ledger API (for writes and reconciliation)
- Optional: PostgreSQL 16 (SQLite is used locally when `DATABASE_URL` is unset)
- Optional: Tesseract with Italian language data for image receipts
- Optional: Docker and Docker Compose

## Quickstart

```bash
git clone <repository-url> expense-tracker
cd expense-tracker
cp .env.example .env
python3.13 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/pip install ../Life/packages/shared ../Life/packages/backend-core
PYTHONPATH=backend .venv/bin/uvicorn expense_tracker_backend.app:app --host 127.0.0.1 --port 10024
```

The framework packages are sibling dependencies in the Life workspace. In CI, the framework is checked out alongside this repository; standalone users need those two packages installed before running the API or tests.

For a portable local stack, copy the example and start it:

```bash
cp deploy/docker-compose.example.yml docker-compose.yml
docker compose up --build
```

## Tests

```bash
PYTHONPATH=backend .venv/bin/python -m pytest
PYTHONPATH=backend .venv/bin/ruff check backend/expense_tracker backend/expense_tracker_backend tests
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `FINANCE_URL` | Finance ledger API base URL |
| `FINANCE_TIMEOUT` | Ledger request timeout |
| `DATABASE_URL` | Database connection URL |
| `EXPENSETRACKER_DATABASE_URL` | Alternative database connection URL |
| `BANK_SELF_NAMES` | Semicolon-separated account-owner names for bank matching |
| `BANK_MEMBER_B_NAMES` | Semicolon-separated second-member names for bank matching |
| `LEGACY_SHARED_SHEET` | Legacy shared-sheet override |
| `LEGACY_PERSONAL_SHEET` | Legacy personal-sheet override |
| `DB_PASSWORD` | Password for the optional Compose database |
| `DB_HOST_PORT` | Host port for the optional Compose database |

## License

MIT. See [LICENSE](LICENSE).
