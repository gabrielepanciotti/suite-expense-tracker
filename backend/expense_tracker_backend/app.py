"""expenseTracker HTTP API.

- `GET  /health` (+ `/api/health`)  — from suite_backend_core, including DB readiness
- `POST /api/import/{kind}`         — upload a document (bank | excel | paypal | bank_pdf | receipt)
- `POST /api/expenses`              — register one expense (default `proposto`) into finance
- `GET  /api/merchant-map`          — the learned classification

Endpoints are plain `def`: the pipeline is synchronous (httpx + sync SQLAlchemy)
and FastAPI runs them in its threadpool.
"""
from __future__ import annotations

import tempfile
from collections.abc import Iterator
from datetime import date as Date
from pathlib import Path
from typing import Annotated, Any, Literal

from expense_tracker import pipeline
from expense_tracker.classify import Classifier
from expense_tracker.domain import Expense, Kind, Payer, Source, Status
from expense_tracker.importers.bank_pdf import parse_bank_pdf
from expense_tracker.importers.bank_xlsx import parse_bbva
from expense_tracker.importers.excel import parse_workbook
from expense_tracker.importers.paypal_csv import parse_paypal
from expense_tracker.importers.receipt import parse_receipt
from expense_tracker.ledger import LedgerClient, LedgerError
from expense_tracker.ocr import OcrEngine, TesseractOcr
from fastapi import Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from suite_backend_core import Settings, create_app

from expense_tracker_backend import config, db
from expense_tracker_backend.finance_client import HttpLedgerClient

app = create_app(Settings(app_name="expense-tracker"), db_ping=db.ping)


# --- dependencies (overridden in tests) ---------------------------------------

def get_ledger() -> Iterator[LedgerClient]:
    client = HttpLedgerClient(config.finance_url(), timeout=config.finance_timeout())
    try:
        yield client
    finally:
        client.close()


def get_ocr() -> Iterator[OcrEngine]:
    yield TesseractOcr()


def get_store() -> Iterator[Any]:
    with db.open_store() as store:
        yield store


def _ledger_down(e: LedgerError) -> HTTPException:
    # finance unreachable/refusing is a gateway failure, never an empty success.
    return HTTPException(status_code=502, detail=str(e))


Ledger = Annotated[LedgerClient, Depends(get_ledger)]
Ocr = Annotated[OcrEngine, Depends(get_ocr)]
Store = Annotated[Any, Depends(get_store)]


# --- schemas ------------------------------------------------------------------

class ExpenseIn(BaseModel):
    date: Date
    description: str = Field(min_length=1)
    amount_cents: int
    source: Source = Source.MANUALE
    category: str | None = None
    kind: Kind | None = None
    shared: bool | None = None
    payer: Payer = Payer.MEMBER_A
    status: Status = Status.PROPOSTO
    note: str | None = None
    payment_method: str | None = None
    buoni_cents: int = Field(default=0, ge=0)
    member_b_share_bp: int | None = Field(default=None, ge=0, le=10000)
    tags: list[str] = Field(default_factory=list)
    seq: int = Field(default=0, ge=0, description="Occurrence index for identical purchases")
    classify: bool = True


class ExpenseOut(BaseModel):
    created: bool
    transaction: dict[str, Any]


class MerchantRuleOut(BaseModel):
    pattern: str
    category: str | None
    kind: str
    shared: bool
    hits: int


# --- routes -------------------------------------------------------------------

_PARSERS = {
    "bank": parse_bbva,
    "excel": parse_workbook,
    "paypal": parse_paypal,
    "bank_pdf": parse_bank_pdf,
}
_SUFFIX = {"bank": ".xlsx", "excel": ".xlsx", "paypal": ".csv", "bank_pdf": ".pdf"}


@app.post("/api/import/{kind}")
def import_document(
    kind: Literal["bank", "excel", "paypal", "bank_pdf", "receipt"],
    file: Annotated[UploadFile, File()],
    ledger: Ledger,
    store: Store,
    ocr: Ocr,
    dry_run: bool = False,
    classify: bool = True,
) -> dict[str, Any]:
    suffix = _SUFFIX[kind] if kind in _SUFFIX else Path(file.filename or "receipt").suffix or ".jpg"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(file.file.read())
        try:
            if kind == "receipt":
                expenses = [parse_receipt(str(path), ocr=ocr)]
            else:
                expenses = _PARSERS[kind](str(path))
        except Exception as e:  # noqa: BLE001 — a bad document is a client error
            raise HTTPException(status_code=422, detail=f"documento non leggibile: {e}") from e
    try:
        if kind == "paypal":
            return pipeline.detail_paypal(expenses, ledger=ledger, dry_run=dry_run)
        if kind == "receipt":
            row, created = pipeline.register_expense(
                expenses[0], ledger=ledger,
                classifier=Classifier(store) if classify else None,
                status=Status.PROPOSTO, dry_run=dry_run,
            )
            return {"created": created, "transaction": row}
        is_bank = kind in ("bank", "bank_pdf")
        summary = pipeline.ingest(
            expenses, ledger=ledger,
            classifier=Classifier(store) if classify and is_bank else None,
            status=Status.PROPOSTO if is_bank else Status.CONFERMATO,
            reconcile_on=is_bank, dry_run=dry_run,
        )
    except LedgerError as e:
        raise _ledger_down(e) from e
    if not dry_run:
        store.log_import(kind=kind, source_file=file.filename or "upload", parsed=summary.parsed,
                         created=summary.created, reconciled=summary.reconciled)
    return summary.as_dict()


@app.post("/api/expenses", status_code=201)
def register_expense(
    body: ExpenseIn,
    response: Response,
    ledger: Ledger,
    store: Store,
    dry_run: bool = False,
) -> ExpenseOut:
    e = Expense(
        date=body.date, description=body.description, amount_cents=body.amount_cents,
        source=body.source, category=body.category, kind=body.kind, shared=body.shared,
        payer=body.payer, note=body.note, payment_method=body.payment_method,
        buoni_cents=body.buoni_cents, member_b_share_bp=body.member_b_share_bp,
        tags=list(body.tags), seq=body.seq,
    )
    try:
        row, created = pipeline.register_expense(
            e, ledger=ledger, classifier=Classifier(store) if body.classify else None,
            status=body.status, dry_run=dry_run,
        )
    except LedgerError as err:
        raise _ledger_down(err) from err
    # Mirrors finance: 201 created, 200 when the raw_hash was already there.
    response.status_code = 201 if created else 200
    return ExpenseOut(created=created, transaction=row)


@app.get("/api/merchant-map")
def merchant_map(store: Store) -> list[MerchantRuleOut]:
    rules = sorted(store.rules(), key=lambda r: (-r.hits, r.pattern))
    return [
        MerchantRuleOut(
            pattern=r.pattern, category=r.category, kind=r.kind, shared=r.shared, hits=r.hits
        )
        for r in rules
    ]
