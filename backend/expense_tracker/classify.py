"""Classifier: propose category/kind/shared from the learned `merchant_map`.

Ported from HomeExpenseSplitter (`classify/engine.py` + `repo.match_merchant`),
with the storage behind a Protocol so the step can be tested with an in-memory
fake and wired to the node's own DB in production.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Protocol

from expense_tracker.domain import Expense, Kind


@dataclass(slots=True)
class MerchantRule:
    pattern: str
    category: str | None
    kind: str
    shared: bool = False
    hits: int = 1


class MerchantStore(Protocol):
    """Where the learned classification lives (owned by expenseTracker)."""

    def rules(self) -> Iterable[MerchantRule]: ...

    def learn(
        self, pattern: str, category: str | None, kind: str, shared: bool
    ) -> MerchantRule: ...


class InMemoryMerchantStore:
    """Fake/dev store. Same semantics as the SQL one."""

    def __init__(self) -> None:
        self._rules: dict[str, MerchantRule] = {}
        self.imports: list[dict[str, object]] = []

    def rules(self) -> list[MerchantRule]:
        return list(self._rules.values())

    def learn(self, pattern: str, category: str | None, kind: str, shared: bool) -> MerchantRule:
        kind = Kind(kind).value
        existing = self._rules.get(pattern)
        if existing is not None:
            # Re-learning updates the mapping (the user may have corrected it) and bumps hits.
            existing.category, existing.kind, existing.shared = category, kind, shared
            existing.hits += 1
            return existing
        rule = MerchantRule(pattern=pattern, category=category, kind=kind, shared=shared)
        self._rules[pattern] = rule
        return rule

    def log_import(self, **entry: object) -> None:
        self.imports.append(dict(entry))


def match_merchant(rules: Iterable[MerchantRule], description: str) -> MerchantRule | None:
    """Rule whose pattern is a case-insensitive substring of `description`.

    Longest pattern wins (most specific); ties broken by more `hits`.
    """
    haystack = description.lower()
    candidates = [r for r in rules if r.pattern.lower() in haystack]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (len(r.pattern), r.hits))


class Classifier:
    """Pipeline step: Expense -> Expense with the learned classification applied."""

    def __init__(self, store: MerchantStore) -> None:
        self.store = store
        self._cache: list[MerchantRule] | None = None

    def _rules(self) -> list[MerchantRule]:
        if self._cache is None:
            self._cache = list(self.store.rules())
        return self._cache

    def classify(self, e: Expense) -> Expense:
        """On a match fill category/kind/shared; otherwise return `e` unchanged (to review)."""
        match = match_merchant(self._rules(), e.description)
        if match is None:
            return e
        return replace(e, category=match.category, kind=Kind(match.kind), shared=match.shared)

    def learn(self, pattern: str, category: str | None, kind: str, shared: bool) -> MerchantRule:
        self._cache = None
        return self.store.learn(pattern, category, kind, shared)
