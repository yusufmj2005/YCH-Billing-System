"""Exact decimal column types for SQLite.

SQLite has no fixed-point type, so money and quantities are stored as
scaled integers (paise, thousandths) and exposed to Python as ``Decimal``.
This avoids floating point rounding errors in financial data.

Note: arithmetic between two scaled columns inside SQL (``a * b``) is not
meaningful; such values are computed in Python and stored explicitly.
SUM / MIN / MAX / comparisons with literals are safe.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.types import Integer, TypeDecorator


class ScaledDecimal(TypeDecorator):
    impl = Integer
    cache_ok = True

    def __init__(self, places: int = 2):
        self.places = places
        super().__init__()

    @property
    def python_type(self):
        return Decimal

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        scaled = (value * (10 ** self.places)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return int(scaled)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(int(value)).scaleb(-self.places)).quantize(Decimal(1).scaleb(-self.places))


def Money() -> ScaledDecimal:
    return ScaledDecimal(2)


def Quantity() -> ScaledDecimal:
    return ScaledDecimal(3)


def Rate() -> ScaledDecimal:
    """Percentage, e.g. 12.5 means 12.5 %."""
    return ScaledDecimal(3)
