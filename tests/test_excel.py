"""Test del parser Excel storico — verificati contro i totali reali del foglio.

I valori attesi derivano dal Riepilogo Finale dell'Excel; il totale condivise
(11.461,66) e personali (4.158,86) combaciano con le righe TOTALE del foglio.
"""
from pathlib import Path

from expense_tracker.domain import Kind, Source
from expense_tracker.importers.excel import parse_workbook

FIXTURE = str(Path(__file__).parent / "fixtures" / "spese_storico.xlsx")

# cache: parse una sola volta
_ROWS = None


def rows():
    global _ROWS
    if _ROWS is None:
        _ROWS = parse_workbook(FIXTURE)
    return _ROWS


# Totali per categoria (centesimi) — Spese Condivise
SHARED_CATEGORY_CENTS = {
    "AFFITTO": 210000,
    "SPESA FISSA MENSILE (100 EUR/mese)": 70000,
    "SUPERMERCATO / ALIMENTARI": 157930,
    "VERDURE MATTIA BRUNI (PayPal)": 40156,
    "KORO ALIMENTARI (PayPal)": 50087,
    "MANDORLE / NOCCIOLE (forfettario)": 15000,
    "BOLLETTE / UTENZE": 160884,
    "CASA / ARREDAMENTO": 32379,
    "VIAGGI - NAPOLI/ROMA (11-12 Ott)": 29261,
    "VIAGGI - PISA (29 Nov)": 26647,
    "VIAGGI - SESTOLA SCI (27-29 Dic)": 44081,
    "VIAGGI - VOLI/PRENOTAZIONI": 20573,
    "RISTORANTI / BAR (locale)": 22252,
    "AMAZON (vari - per casa?)": 84478,
    "SPETTACOLI / CINEMA": 1600,
    "TECNOLOGIA / ELETTRONICA (condivisa)": 48329,
    "ANIMALI / MICIA (condivisa)": 25648,
    "ACQUISTI VARI (condivisi)": 103267,
    "GOOGLE PLAY APPS": 3594,
}


def _sum(category):
    return sum(r.amount_cents for r in rows() if r.category == category)


def test_shared_category_totals_match_riepilogo():
    for cat, expected in SHARED_CATEGORY_CENTS.items():
        assert _sum(cat) == expected, f"{cat}: atteso {expected}, ottenuto {_sum(cat)}"


def test_shared_grand_total():
    shared = [r for r in rows() if r.kind == Kind.SPESA_CONDIVISA]
    assert sum(r.amount_cents for r in shared) == 1146166  # 11.461,66 €


def test_personal_grand_total():
    personal = [r for r in rows() if r.kind == Kind.SPESA_PERSONALE]
    assert sum(r.amount_cents for r in personal) == 415886  # 4.158,86 €


def test_affitto_row_count():
    assert len([r for r in rows() if r.category == "AFFITTO"]) == 6


def test_carburante_personal_count():
    carb = [r for r in rows() if r.category == "CARBURANTE (quotidiano)"]
    assert len(carb) == 19
    assert all(r.kind == Kind.SPESA_PERSONALE for r in carb)


def test_datetime_date_cell_is_parsed():
    """La riga 'Skipass' (Contanti) ha la data come datetime Excel reale:
    deve comunque finire in VIAGGI SESTOLA, altrimenti il totale scende di 300€."""
    sestola = [r for r in rows() if r.category == "VIAGGI - SESTOLA SCI (27-29 Dic)"]
    assert len(sestola) == 15
    skipass = [r for r in sestola if r.amount_cents == 30000]
    assert len(skipass) == 1
    assert skipass[0].source is Source.CONTANTI


def test_no_total_or_header_rows():
    for r in rows():
        assert r.description.strip().upper() not in ("TOTALE", "DATA")
        assert r.amount_cents != 0
        assert r.date is not None


def test_categories_are_not_merged():
    """Regressione: l'euristica tutto-maiuscolo fondeva AFFITTO+SPESA FISSA."""
    assert len([r for r in rows() if r.category == "AFFITTO"]) == 6
    assert len([r for r in rows() if r.category == "SPESA FISSA MENSILE (100 EUR/mese)"]) == 7
