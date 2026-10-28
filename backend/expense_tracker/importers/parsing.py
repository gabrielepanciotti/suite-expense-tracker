# expense_tracker/importers/parsing.py
from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal

_AMOUNT_RE = re.compile(r"-?\d[\d.,]*")


def env_names(var: str) -> list[str]:
    """Casefolded name list from a ";"-separated env var (device-local, untracked)."""
    return [p.strip().casefold() for p in os.environ.get(var, "").split(";") if p.strip()]


def collapse_ws(s: str | None) -> str:
    """Comprime i run di whitespace e fa strip (merchant stringhe paddate)."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def parse_bbva_amount(raw: object) -> int:
    """Importo BBVA → centesimi signed.

    In questo estratto il separatore (punto o virgola) è SEMPRE il decimale —
    non ci sono separatori delle migliaia — con 1 o 2 cifre decimali:
    ``-66.6 EUR`` = -66,60 · ``-16.83 EUR`` = -16,83 · ``2435 EUR`` = 2435,00.
    NB: il parser generico ``parse_amount_cents`` interpreterebbe ``66.6`` come
    migliaia (decimale solo se 2 cifre) → bug ×10. Qui prendiamo l'ultimo
    separatore come decimale e ignoriamo qualsiasi altra cosa non numerica.
    """
    text = str(raw).replace("EUR", "").replace("€", "").replace(" ", " ").strip()
    neg = text.startswith("-")
    text = text.lstrip("+-").strip()
    sep_idx = max(text.rfind("."), text.rfind(","))
    if sep_idx >= 0:
        int_part = re.sub(r"\D", "", text[:sep_idx])
        frac = (re.sub(r"\D", "", text[sep_idx + 1:]) + "00")[:2]
    else:
        int_part, frac = re.sub(r"\D", "", text), "00"
    if not int_part:
        raise ValueError(f"importo BBVA non riconosciuto: {raw!r}")
    cents = int(int_part) * 100 + int(frac or "0")
    return -cents if neg else cents


def _detect_decimal_sep(token: str) -> str | None:
    """Return the decimal separator for a numeric token (no sign, no spaces).

    Rules (Italian + US mixed bank/Excel data):
    - If BOTH '.' and ',' appear → the last-occurring one is the decimal
      separator; the other is a thousands separator.
    - If only ONE separator appears → it is the decimal separator ONLY if it
      is followed by exactly 2 digits; otherwise it is a thousands separator
      and the number has no decimals.
    - No separator → no decimals.
    """
    has_dot = "." in token
    has_comma = "," in token

    if has_dot and has_comma:
        # Last separator wins as decimal
        last_dot = token.rfind(".")
        last_comma = token.rfind(",")
        return "." if last_dot > last_comma else ","

    sep = "." if has_dot else ("," if has_comma else None)
    if sep is None:
        return None

    # Single separator: decimal only if followed by exactly 2 digits
    idx = token.rfind(sep)
    after = token[idx + 1:]
    if len(after) == 2 and after.isdigit():
        return sep
    # Otherwise it is a thousands separator → no decimal part
    return None


def parse_amount_cents(raw: str | float | int) -> int:
    """Converte '2,100.00 EUR' / '-29,80' / 8.35 in centesimi interi (signed).

    Regole: se entrambi '.' e ',' presenti, l'ultimo è il decimale; se uno
    solo, è decimale solo se seguito da esattamente 2 cifre; altrimenti è
    separatore migliaia. Numeri interi/float via Decimal per evitare errori
    IEEE-754.
    """
    if isinstance(raw, bool):
        raise ValueError(f"importo non riconosciuto: {raw!r}")
    if isinstance(raw, int):
        return raw * 100
    if isinstance(raw, float):
        return int((Decimal(str(raw)) * 100).to_integral_value())

    text = raw.strip().replace("EUR", "").replace("€", "").strip()
    m = _AMOUNT_RE.search(text)
    if not m:
        raise ValueError(f"importo non riconosciuto: {raw!r}")
    token = m.group(0)
    neg = token.startswith("-")
    token = token.lstrip("-")

    dec_sep = _detect_decimal_sep(token)

    if dec_sep is not None:
        idx = token.rfind(dec_sep)
        thou_sep = "." if dec_sep == "," else ","
        int_part = token[:idx].replace(thou_sep, "").replace(dec_sep, "")
        frac_part = token[idx + 1:]
    else:
        # No decimal — strip all separators
        int_part = token.replace(".", "").replace(",", "")
        frac_part = "00"

    cents = int(int_part or "0") * 100 + int(frac_part or "0")
    return -cents if neg else cents


def parse_date(raw: str) -> date | None:
    """Parse 'dd/mm/yyyy' o 'dd/mm' (anno assente → None). Mesi a parole → None."""
    text = (raw or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
