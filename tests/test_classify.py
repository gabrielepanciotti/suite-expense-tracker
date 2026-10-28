"""Classifier on merchant_map (ported from HES test_classify), run on both stores."""
from datetime import date

import pytest
from expense_tracker.classify import Classifier, InMemoryMerchantStore
from expense_tracker.domain import Expense, Kind, Source


def _raw(desc: str, cents: int = 1004) -> Expense:
    return Expense(date=date(2025, 10, 2), description=desc, amount_cents=cents,
                   source=Source.BANCA, kind=Kind.SPESA_PERSONALE)


@pytest.fixture(params=["memory", "sql"])
def any_store(request, sql_store):
    return InMemoryMerchantStore() if request.param == "memory" else sql_store


def test_known_pattern_fills_category_kind_shared(any_store):
    any_store.learn("UNICOOP", "SUPERMERCATO / ALIMENTARI", "spesa_condivisa", True)
    out = Classifier(any_store).classify(_raw("UNICOOP ETRURIA SC"))
    assert out.category == "SUPERMERCATO / ALIMENTARI"
    assert out.kind == Kind.SPESA_CONDIVISA
    assert out.shared is True
    assert out.description == "UNICOOP ETRURIA SC"
    assert out.amount_cents == 1004
    assert out.source == Source.BANCA


def test_unknown_merchant_returned_unchanged(any_store):
    any_store.learn("UNICOOP", "SUPERMERCATO / ALIMENTARI", "spesa_condivisa", True)
    out = Classifier(any_store).classify(_raw("SOME UNKNOWN SHOP"))
    assert out.category is None
    assert out.kind == Kind.SPESA_PERSONALE
    assert out.shared is None


def test_paypal_to_detail_stays_to_review(any_store):
    any_store.learn("UNICOOP", "SUPERMERCATO / ALIMENTARI", "spesa_condivisa", True)
    out = Classifier(any_store).classify(_raw("PayPal (da dettagliare)"))
    assert out.category is None and out.shared is None


def test_longest_pattern_wins(any_store):
    any_store.learn("AMAZON", "VARIE", "spesa_personale", False)
    any_store.learn("AMAZON PRIME", "ABBONAMENTI", "spesa_personale", True)
    out = Classifier(any_store).classify(_raw("PAGAMENTO AMAZON PRIME VIDEO"))
    assert out.category == "ABBONAMENTI"
    assert out.shared is True


def test_tie_break_prefers_higher_hits(any_store):
    any_store.learn("Q8FOO", "CARBURANTE", "spesa_personale", False)
    any_store.learn("Q8BAR", "PARCHEGGIO", "spesa_personale", False)
    any_store.learn("Q8BAR", "PARCHEGGIO", "spesa_personale", False)
    out = Classifier(any_store).classify(_raw("PAGAMENTO Q8FOO Q8BAR STATION"))
    assert out.category == "PARCHEGGIO"


def test_case_insensitive_match(any_store):
    any_store.learn("amazon", "VARIE", "spesa_personale", False)
    assert Classifier(any_store).classify(_raw("PAGAMENTO AMAZON IT")).category == "VARIE"


def test_empty_merchant_map_returns_input_unchanged(any_store):
    out = Classifier(any_store).classify(_raw("ANYTHING AT ALL"))
    assert out.category is None and out.kind == Kind.SPESA_PERSONALE and out.shared is None


def test_learn_merchant_updates_existing(any_store):
    any_store.learn("ESSELUNGA", "SPESA", "spesa_personale", False)
    rule = any_store.learn("ESSELUNGA", "SUPERMERCATO", "spesa_condivisa", True)
    assert (rule.category, rule.kind, rule.shared, rule.hits) == (
        "SUPERMERCATO", "spesa_condivisa", True, 2)
    assert len(list(any_store.rules())) == 1


def test_learn_rejects_unknown_kind(any_store):
    with pytest.raises(ValueError):
        any_store.learn("X", "Y", "non_esiste", False)


def test_classifier_learn_invalidates_cache(any_store):
    c = Classifier(any_store)
    assert c.classify(_raw("NEW SHOP")).category is None
    c.learn("NEW SHOP", "VARIE", "spesa_personale", False)
    assert c.classify(_raw("NEW SHOP")).category == "VARIE"
