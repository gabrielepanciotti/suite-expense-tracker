"""expenseTracker CLI — `python -m expense_tracker_backend.cli <command>`.

Composition root for the terminal: wires the importers, the classifier on the
node's merchant_map, and the finance ledger. Every command accepts `--dry-run`
(reads finance to reconcile/dedupe, writes nothing anywhere).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from expense_tracker import pipeline
from expense_tracker.classify import Classifier
from expense_tracker.domain import Expense, Kind, Payer, Source, Status
from expense_tracker.importers.bank_pdf import parse_bank_pdf
from expense_tracker.importers.bank_xlsx import parse_bbva
from expense_tracker.importers.excel import parse_workbook
from expense_tracker.importers.parsing import parse_amount_cents, parse_date
from expense_tracker.importers.paypal_csv import parse_paypal
from expense_tracker.importers.receipt import parse_receipt
from expense_tracker.ledger import LedgerClient, LedgerError
from expense_tracker.ocr import OcrEngine, OcrError, TesseractOcr

from expense_tracker_backend import config, db
from expense_tracker_backend.finance_client import HttpLedgerClient

app = typer.Typer(
    help="expenseTracker — cattura le uscite e le scrive in finance", no_args_is_help=True
)

DRY_RUN = typer.Option(False, "--dry-run", help="Legge finance ma non scrive nulla")


# --- wiring (tests monkeypatch these) ----------------------------------------

def make_ledger() -> LedgerClient:
    return HttpLedgerClient(config.finance_url(), timeout=config.finance_timeout())


def make_ocr() -> OcrEngine:
    return TesseractOcr()


@contextmanager
def store_ctx() -> Iterator[Any]:
    with db.open_store() as store:
        yield store


def _fail(e: Exception) -> None:
    typer.echo(f"ERRORE: {e}", err=True)
    raise typer.Exit(1)


def _print_summary(summary: pipeline.ImportSummary, *, verb: str = "nuove") -> None:
    prefix = "[dry-run] " if summary.dry_run else ""
    typer.echo(
        f"{prefix}Lette {summary.parsed} righe: {summary.created} {verb}, "
        f"{summary.existing} già in finance, {summary.reconciled} riconciliate con uno "
        f"scontrino, {summary.already_reconciled} già riconciliate."
    )
    for k, n in sorted(summary.per_kind.items()):
        typer.echo(f"  [{k:16s}] {n}")


def _import(kind: str, path: str, expenses: list[Expense], *, status: Status,
            classify_on: bool, reconcile_on: bool, dry_run: bool) -> None:
    ledger = make_ledger()
    try:
        with store_ctx() as store:
            summary = pipeline.ingest(
                expenses, ledger=ledger, classifier=Classifier(store) if classify_on else None,
                status=status, reconcile_on=reconcile_on, dry_run=dry_run,
            )
            if not dry_run:
                store.log_import(kind=kind, source_file=Path(path).name, parsed=summary.parsed,
                                 created=summary.created, reconciled=summary.reconciled)
    except LedgerError as e:
        _fail(e)
    _print_summary(summary)


@app.command("import-bank")
def import_bank(
    path: str = typer.Argument(..., help="Estratto conto BBVA .xlsx"),
    no_classify: bool = typer.Option(False, "--no-classify", help="Non applicare il merchant_map"),
    dry_run: bool = DRY_RUN,
) -> None:
    """Estratto conto -> proposte in finance, riconciliando gli scontrini in attesa."""
    _import("bank", path, parse_bbva(path), status=Status.PROPOSTO,
            classify_on=not no_classify, reconcile_on=True, dry_run=dry_run)


@app.command("import-bank-pdf")
def import_bank_pdf(
    path: str = typer.Argument(..., help="Estratto conto banca .pdf"),
    no_classify: bool = typer.Option(False, "--no-classify", help="Non applicare il merchant_map"),
    dry_run: bool = DRY_RUN,
) -> None:
    """Estratto conto PDF -> proposte in finance, riconciliando gli scontrini in attesa."""
    _import("bank_pdf", path, parse_bank_pdf(path), status=Status.PROPOSTO,
            classify_on=not no_classify, reconcile_on=True, dry_run=dry_run)


@app.command("import-excel")
def import_excel(
    path: str = typer.Argument(..., help="Workbook storico delle spese .xlsx"),
    dry_run: bool = DRY_RUN,
) -> None:
    """Storico Excel -> finance come righe `confermato` (già riviste a suo tempo)."""
    _import("excel", path, parse_workbook(path), status=Status.CONFERMATO,
            classify_on=False, reconcile_on=False, dry_run=dry_run)


@app.command("import-paypal")
def import_paypal(
    path: str = typer.Argument(..., help="Export PayPal .csv"),
    dry_run: bool = DRY_RUN,
) -> None:
    """Dettaglia le proposte banca `PayPal (da dettagliare)` col merchant reale."""
    ledger = make_ledger()
    try:
        summary = pipeline.detail_paypal(parse_paypal(path), ledger=ledger, dry_run=dry_run)
    except LedgerError as e:
        _fail(e)
    prefix = "[dry-run] " if dry_run else ""
    typer.echo(
        f"{prefix}{summary['detailed']} proposte dettagliate "
        f"({summary['identified']} con merchant, {summary['generic']} generiche)."
    )
    if summary["unmatched_proposals"]:
        typer.echo(f"  ATTENZIONE: {summary['unmatched_proposals']} proposte PayPal non abbinate.")


@app.command("add")
def add(
    desc: str = typer.Option(..., "--desc", help="Descrizione"),
    amount: str = typer.Option(..., "--amount", help="Importo, es. 150 o 150,00"),
    date_str: str = typer.Option(..., "--date", help="Data dd/mm/yyyy"),
    kind: str = typer.Option(None, "--kind", help="spesa_condivisa|spesa_personale|..."),
    category: str = typer.Option(None, "--category", help="Categoria"),
    shared: bool = typer.Option(None, "--shared/--personal", help="Condivisa o personale"),
    buoni: str = typer.Option(None, "--buoni", help="Quota pagata in buoni pasto"),
    payment_method: str = typer.Option(None, "--payment-method", help="carta|contanti|misto|..."),
    source: str = typer.Option("manuale", "--source", help="manuale|contanti|screenshot"),
    payer: str = typer.Option("member_a", "--payer", help="member_a|member_b"),
    note: str = typer.Option(None, "--note"),
    confirmed: bool = typer.Option(
        False, "--confirmed", help="Registra già confermata (contanti: nessuna banca da attendere)"
    ),
    dry_run: bool = DRY_RUN,
) -> None:
    """Registra UNA spesa, di default `proposto` in attesa della riga di banca."""
    d = parse_date(date_str)
    if d is None:
        raise typer.BadParameter(f"data non valida: {date_str}")
    try:
        e = Expense(
            date=d, description=desc, amount_cents=parse_amount_cents(amount),
            source=Source(source), category=category, kind=Kind(kind) if kind else None,
            shared=shared, payer=Payer(payer), note=note, payment_method=payment_method,
            buoni_cents=parse_amount_cents(buoni) if buoni else 0,
        )
    except ValueError as err:
        raise typer.BadParameter(str(err)) from err
    status = Status.CONFERMATO if confirmed else Status.PROPOSTO
    ledger = make_ledger()
    try:
        with store_ctx() as store:
            row, created = pipeline.register_expense(
                e, ledger=ledger, classifier=Classifier(store), status=status, dry_run=dry_run
            )
    except LedgerError as err:
        _fail(err)
    prefix = "[dry-run] " if dry_run else ""
    esito = "registrata" if created else "già presente"
    typer.echo(
        f"{prefix}Spesa {esito} ({row.get('status')}): {d} {desc} "
        f"{e.amount_cents / 100:,.2f} EUR [{row.get('kind') or '?'}/{row.get('category') or '-'}]"
    )


@app.command("import-receipt")
def import_receipt(
    path: str = typer.Argument(..., help="Foto o PDF di uno scontrino"),
    confirmed: bool = typer.Option(
        False, "--confirmed", help="Registra già confermato (contanti: nessuna banca da attendere)"
    ),
    dry_run: bool = DRY_RUN,
) -> None:
    """Legge uno scontrino (OCR) -> una spesa `proposto` in attesa della riga di banca."""
    try:
        e = parse_receipt(path, make_ocr())
    except (OcrError, ValueError) as err:
        _fail(err)
    status = Status.CONFERMATO if confirmed else Status.PROPOSTO
    ledger = make_ledger()
    try:
        with store_ctx() as store:
            row, created = pipeline.register_expense(
                e, ledger=ledger, classifier=Classifier(store), status=status, dry_run=dry_run
            )
    except LedgerError as err:
        _fail(err)
    prefix = "[dry-run] " if dry_run else ""
    esito = "registrato" if created else "già presente"
    typer.echo(
        f"{prefix}Scontrino {esito} ({row.get('status')}): {e.date or '?'} {e.description} "
        f"{e.amount_cents / 100:,.2f} EUR [{row.get('kind') or '?'}/{row.get('category') or '-'}]"
    )


@app.command("review")
def review(dry_run: bool = DRY_RUN) -> None:
    """Rivede le proposte in finance: conferma/corregge e (opzionale) impara il merchant."""
    ledger = make_ledger()
    try:
        pending = pipeline.pending_proposals(ledger)
    except LedgerError as e:
        _fail(e)
    if not pending:
        typer.echo("Nessuna proposta da rivedere.")
        return
    typer.echo(f"{len(pending)} proposte da rivedere.\n")
    with store_ctx() as store:
        classifier = Classifier(store)
        for row in pending:
            typer.echo(
                f"{row.get('date')}  {row.get('description')}  "
                f"{(row.get('amount_cents') or 0) / 100:>10,.2f} EUR  "
                f"[{row.get('kind') or '?'}/{row.get('category') or '-'}"
                f"{'/cond' if row.get('shared') else ''}]"
            )
            action = typer.prompt(
                "  (Invio=conferma · c=correggi · s=salta · q=esci)", default="", show_default=False
            ).strip().lower()
            if action == "q":
                typer.echo("Interrotto.")
                break
            if action == "s":
                continue
            category, kind, shared = row.get("category"), row.get("kind"), bool(row.get("shared"))
            if action == "c" or not kind:
                kind = typer.prompt("  kind", default=kind or "spesa_personale")
                category = typer.prompt("  categoria", default=category or "") or None
                shared = typer.confirm("  condivisa?", default=shared)
            learn_pattern = None
            if typer.confirm("  imparare il merchant?", default=False):
                suggested = row.get("description") if row.get("source") == "banca" else ""
                learn_pattern = typer.prompt("  pattern", default=suggested or "") or None
            try:
                pipeline.confirm_proposal(
                    row, ledger=ledger, classifier=classifier, category=category, kind=kind,
                    shared=shared, learn_pattern=learn_pattern, dry_run=dry_run,
                )
            except ValueError:
                typer.echo(f"  kind non valido: {kind} — saltata.")
            except LedgerError as e:
                _fail(e)
    typer.echo("Review completata." + (" (dry-run: nulla scritto)" if dry_run else ""))


@app.command("merchant-map")
def merchant_map() -> None:
    """Elenca la classificazione imparata."""
    with store_ctx() as store:
        rules = sorted(store.rules(), key=lambda r: (-r.hits, r.pattern))
    for r in rules:
        typer.echo(f"{r.pattern:30s} -> {r.kind}/{r.category or '-'}"
                   f"{' cond' if r.shared else ''} ({r.hits})")
    if not rules:
        typer.echo("merchant_map vuota.")


if __name__ == "__main__":
    app()
