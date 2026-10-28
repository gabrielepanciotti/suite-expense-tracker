from datetime import date

from expense_tracker.importers.parsing import parse_amount_cents, parse_date


def test_parse_amount_basic():
    assert parse_amount_cents("350.00 EUR") == 35000


def test_parse_amount_thousands_separator():
    assert parse_amount_cents("2,100.00 EUR") == 210000


def test_parse_amount_negative():
    assert parse_amount_cents("-29.80 EUR") == -2980


def test_parse_amount_plain_number():
    assert parse_amount_cents("8,35") == 835


def test_parse_date_full():
    assert parse_date("16/10/2025") == date(2025, 10, 16)


def test_parse_date_unparseable_returns_none():
    assert parse_date("Novembre") is None


# Fix 1 — thousands separator without decimals
def test_parse_amount_thousands_no_decimals():
    assert parse_amount_cents("1.000") == 100000
    assert parse_amount_cents("10.000") == 1000000


def test_parse_amount_italian_full():
    assert parse_amount_cents("1.234,56") == 123456


def test_parse_amount_us_thousands_with_decimals():
    assert parse_amount_cents("2,100.00 EUR") == 210000


# Fix 2 — float precision via Decimal
def test_parse_amount_float_precision():
    assert parse_amount_cents(186.9) == 18690
    assert parse_amount_cents(350.0) == 35000
