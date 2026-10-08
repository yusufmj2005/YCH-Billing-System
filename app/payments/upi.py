"""UPI payment QR codes (record-keeping only; no gateway).

Builds a standard ``upi://pay`` link with the shop's UPI ID and the exact
amount. Any UPI app (GPay, PhonePe, Paytm, BHIM, ...) can scan it. The money
goes straight to the shop's bank account; BusinessPOS only shows the code and
records the payment the cashier confirms.
"""
from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import quote

from reportlab.graphics.barcode import qrencoder

from app.services.errors import ValidationError
from app.utils.money import money

# handle@bank, e.g. yarnshop@okaxis, 9876543210@ybl, shop.name-1@paytm
_VPA_RE = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9.-]{1,63}$")


def validate_upi_id(value) -> str:
    """Return the cleaned UPI ID ('' when blank) or raise ValidationError."""
    s = ("" if value is None else str(value)).strip()
    if s and not _VPA_RE.match(s):
        raise ValidationError(
            "UPI ID must look like name@bank (for example yarnshop@okaxis).")
    return s


def upi_uri(upi_id: str, payee_name: str, amount, note: str = "") -> str:
    """``upi://pay`` link for a fixed amount in INR (amount rounded to paise)."""
    upi_id = validate_upi_id(upi_id)
    if not upi_id:
        raise ValidationError("Set the shop's UPI ID in Settings › Payments first.")
    amt = money(amount)
    if amt <= Decimal(0):
        raise ValidationError("The UPI amount must be greater than zero.")
    parts = [f"pa={quote(upi_id, safe='@')}",
             f"pn={quote((payee_name or '').strip()[:50] or upi_id, safe='')}",
             f"am={amt:.2f}", "cu=INR"]
    if note.strip():
        parts.append(f"tn={quote(note.strip()[:50], safe='')}")
    return "upi://pay?" + "&".join(parts)


def qr_matrix(text: str) -> list[list[bool]]:
    """QR code modules (True = dark) for ``text``, error correction level M."""
    code = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
    code.addData(text)
    code.make()
    n = code.getModuleCount()
    return [[bool(code.isDark(r, c)) for c in range(n)] for r in range(n)]
