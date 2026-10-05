"""Decimal helpers. All money is handled as ``Decimal`` — never float."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ZERO = Decimal("0")
CENT = Decimal("0.01")
MILLI = Decimal("0.001")


def D(value) -> Decimal:
    """Convert ``value`` to Decimal (``None``/'' -> 0). Raises ValueError."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid number: {value!r}") from exc


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def qty(value) -> Decimal:
    return D(value).quantize(MILLI, rounding=ROUND_HALF_UP)


def fmt_money(value, symbol: str = "") -> str:
    v = money(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    whole, frac = f"{v:.2f}".split(".")
    # Indian digit grouping: 12,34,567.89
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{symbol}{whole}.{frac}"


def fmt_qty(value) -> str:
    v = qty(value)
    if v == v.to_integral_value():
        return str(int(v))
    return f"{v.normalize():f}"
