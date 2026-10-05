"""Barcode value helpers.

Generated values follow a configurable strategy:
* CODE128: ``<prefix><8-digit sequence>``
* EAN13:   ``<numeric prefix, default '20'><sequence>`` padded to 12 digits
           + check digit. Prefixes 20-29 are reserved by GS1 for in-store
           (restricted circulation) use, so they never clash with codes
           printed by manufacturers.
Values are only generated when a user explicitly asks for one.
"""
from __future__ import annotations

from app.services.errors import ValidationError


def ean13_check_digit(first12: str) -> str:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("EAN-13 body must be 12 digits")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid_ean13(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == code[12]


def make_code(symbology: str, prefix: str, sequence: int) -> str:
    if symbology == "EAN13":
        prefix = prefix or "20"
        if not prefix.isdigit():
            raise ValidationError("EAN-13 barcode prefix must contain digits only.")
        body_len = 12 - len(prefix)
        if body_len < 4:
            raise ValidationError("EAN-13 barcode prefix is too long.")
        if sequence >= 10 ** body_len:
            raise ValidationError("Barcode sequence exhausted for this prefix.")
        body = f"{prefix}{sequence:0{body_len}d}"
        return body + ean13_check_digit(body)
    return f"{prefix}{sequence:08d}"
