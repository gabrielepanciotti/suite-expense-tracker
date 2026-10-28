"""The one type that travels through the capture chain: `Expense`.

Born in an importer (or in a manual registration), enriched by the classifier,
consumed by the reconciler/writer. Ported from HomeExpenseSplitter's
`RawTransaction`, with one deliberate cut: the status `rimborsato` does not
exist here. Being reimbursed by member B is a *split* concern and stays in
homeExpenseSplitter; capture only knows `proposto` and `confermato`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Source(StrEnum):
    BANCA = "banca"
    PAYPAL = "paypal"
    MANUALE = "manuale"
    SCREENSHOT = "screenshot"
    CONTANTI = "contanti"
    SCONTRINO = "scontrino"


class Kind(StrEnum):
    SPESA_CONDIVISA = "spesa_condivisa"
    SPESA_PERSONALE = "spesa_personale"
    ENTRATA = "entrata"
    INVESTIMENTO = "investimento"
    MEMBER_TRANSFER = "member_transfer"
    GIROCONTO = "giroconto"  # transfers between own accounts: not an expense nor income


# Kinds that are an actual outgoing expense (the only ones a receipt can match).
EXPENSE_KINDS = frozenset({Kind.SPESA_CONDIVISA, Kind.SPESA_PERSONALE})

# Sources that come from a bank-side document: a row from them is the "bank
# line", never the "receipt" awaiting it.
BANK_SOURCES = frozenset({Source.BANCA, Source.PAYPAL})


class Status(StrEnum):
    """Capture status. `rimborsato` is intentionally absent (it belongs to the splitter)."""

    PROPOSTO = "proposto"
    CONFERMATO = "confermato"


class ReconStatus(StrEnum):
    NESSUNA = "nessuna"
    AUTO = "auto"
    CONFERMATA = "confermata"


class Payer(StrEnum):
    MEMBER_A = "member_a"
    MEMBER_B = "member_b"


@dataclass(slots=True)
class Expense:
    """A captured movement, before it is written to finance.

    `amount_cents` follows the ledger convention inherited from
    HomeExpenseSplitter: for expenses it is the cost (positive magnitude),
    refunds negative; member_transfer/giroconto keep the bank sign. Expenses
    and income are told apart by `kind`, never by the sign alone.
    """

    date: date | None
    description: str
    amount_cents: int
    source: Source
    category: str | None = None
    kind: Kind | None = None
    shared: bool | None = None
    payer: Payer = Payer.MEMBER_A
    note: str | None = None
    payment_method: str | None = None
    buoni_cents: int = 0
    member_b_share_bp: int | None = None
    tags: list[str] = field(default_factory=list)
    seq: int = 0  # occurrence index among otherwise identical rows (dedup-safe)

    @property
    def raw_hash(self) -> str:
        return raw_hash(self)

    @property
    def card_amount_cents(self) -> int:
        """What actually left the card: total minus the meal-voucher share."""
        return self.amount_cents - (self.buoni_cents or 0)


def raw_hash(e: Expense) -> str:
    """Idempotency key sent to finance — byte-identical to HomeExpenseSplitter.

    Keeping the exact formula means a statement already imported by HES (whose
    rows finance inherits) is recognised as "already there" instead of being
    duplicated. `kind`/`shared` are excluded on purpose: reclassifying must not
    break re-import idempotency; `seq` separates otherwise identical rows.
    """
    key = f"{e.date}|{e.description.strip().lower()}|{e.amount_cents}|{e.source.value}|{e.seq}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def assign_seq(expenses: list[Expense], *, with_source: bool = False) -> list[Expense]:
    """Set `seq` = occurrence index among rows sharing (date, description, amount[, source])."""
    seen: dict[tuple, int] = {}
    for e in expenses:
        key: tuple = (e.date, e.description, e.amount_cents)
        if with_source:
            key += (e.source.value,)
        e.seq = seen.get(key, 0)
        seen[key] = e.seq + 1
    return expenses
