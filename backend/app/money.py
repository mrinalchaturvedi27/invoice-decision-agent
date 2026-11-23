import re
from decimal import Decimal, InvalidOperation

_STRIP = re.compile(r"[^\d.\-]")


def D(value) -> Decimal | None:
    """Parse a money/quantity value ("20,000.00", "$50", 400) into Decimal; None if absent/unparseable."""
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


def fmt(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def s(value: Decimal | None) -> str | None:
    """Serialise a Decimal for storage/JSON."""
    return None if value is None else str(value)
