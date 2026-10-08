"""Input normalisation/validation shared by services."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from app.services.errors import ValidationError
from app.utils.money import D, money, qty

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[0-9+\-() ]{5,20}$")
# GSTIN: 2 digit state + 10 char PAN + entity + 'Z' + checksum
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]Z[0-9A-Z]$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def text(value, label: str, *, required: bool = False, max_len: int | None = None) -> str | None:
    s = ("" if value is None else str(value)).strip()
    if not s:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if max_len and len(s) > max_len:
        raise ValidationError(f"{label} must be at most {max_len} characters.")
    return s


def email(value, label: str = "Email") -> str | None:
    s = text(value, label, max_len=150)
    if s and not _EMAIL_RE.match(s):
        raise ValidationError(f"{label} is not a valid email address.")
    return s


def phone(value, label: str = "Phone") -> str | None:
    s = text(value, label, max_len=20)
    if s and not _PHONE_RE.match(s):
        raise ValidationError(f"{label} may contain only digits, spaces and + - ( ).")
    return s


def gstin(value, label: str = "GSTIN") -> str | None:
    s = text(value, label, max_len=15)
    if s:
        s = s.upper()
        if not _GSTIN_RE.match(s):
            raise ValidationError(f"{label} must be a 15-character GSTIN (e.g. format 22AAAAA0000A1Z5).")
    return s


def decimal(value, label: str, *, required: bool = True, min_value=None, max_value=None,
            allow_zero: bool = True, places: int = 2) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    try:
        v = D(value)
    except ValueError:
        raise ValidationError(f"{label} must be a number.") from None
    if not v.is_finite():
        raise ValidationError(f"{label} must be a number.")
    if v and v.adjusted() >= 15:  # far beyond any real amount; also keeps quantize in range
        raise ValidationError(f"{label} is too large.")
    if v.as_tuple().exponent < -places and v != v.quantize(Decimal(1).scaleb(-places)):
        raise ValidationError(f"{label} allows at most {places} decimal places.")
    if not allow_zero and v == 0:
        raise ValidationError(f"{label} must not be zero.")
    if min_value is not None and v < D(min_value):
        raise ValidationError(f"{label} must be at least {min_value}.")
    if max_value is not None and v > D(max_value):
        raise ValidationError(f"{label} must be at most {max_value}.")
    return money(v) if places == 2 else qty(v)


def amount(value, label: str = "Amount", *, required: bool = True, positive: bool = False):
    v = decimal(value, label, required=required, min_value=0, allow_zero=not positive)
    return v


def quantity(value, label: str = "Quantity", *, allow_fraction: bool = True) -> Decimal:
    v = decimal(value, label, min_value=0, allow_zero=False, places=3)
    if v <= 0:
        raise ValidationError(f"{label} must be greater than zero.")
    if not allow_fraction and v != v.to_integral_value():
        raise ValidationError(f"{label} must be a whole number for this product.")
    return v


def percent(value, label: str, *, required: bool = True) -> Decimal | None:
    v = decimal(value, label, required=required, min_value=0, max_value=100, places=3)
    return v


def as_date(value, label: str, *, required: bool = True) -> date | None:
    if value is None or value == "":
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError(f"{label} is not a valid date.") from None


def hhmm(value, label: str) -> str | None:
    s = text(value, label)
    if s and not _TIME_RE.match(s):
        raise ValidationError(f"{label} must be a time in HH:MM (24-hour) format.")
    return s


def barcode_value(value) -> str | None:
    s = text(value, "Barcode", max_len=64)
    if s and not re.fullmatch(r"[\x21-\x7E]+", s):
        raise ValidationError("Barcode may only contain printable characters without spaces.")
    return s
