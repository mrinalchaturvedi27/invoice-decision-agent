import re
from decimal import Decimal, InvalidOperation

from app.policy import LEDGER_CURRENCY

_STRIP = re.compile(r"[^\d.\-]")
_INDIAN_GROUPS = re.compile(r"(?<=\d)(?=(?:\d{2})*\d{3}$)")


def D(value) -> Decimal | None:
    """Parse a money or quantity value into Decimal, or return None if it cannot be read."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = _STRIP.sub("", str(value))
    if s in ("", "-", ".", "-."):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def fmt(value: Decimal | None, currency: str | None = LEDGER_CURRENCY) -> str:
    if value is None:
        return "—"
    if currency == "INR":
        whole, fraction = f"{abs(value):.2f}".split(".")
        sign = "-" if value < 0 else ""
        return f"{sign}₹{_INDIAN_GROUPS.sub(',', whole)}.{fraction}"
    return f"{currency} {value:,.2f}" if currency else f"{value:,.2f}"


def s(value: Decimal | None) -> str | None:
    """Serialise a Decimal for storage/JSON."""
    return None if value is None else str(value)
