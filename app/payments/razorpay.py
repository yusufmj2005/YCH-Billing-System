"""Razorpay: collect a payment at checkout and confirm it automatically.

Two ways to pay, both confirmed by asking Razorpay (polling); BusinessPOS needs
no web server or webhook:

* **UPI QR** - a single-use Razorpay QR code for the exact amount
  (``/v1/payments/qr_codes``). The customer scans it with any UPI app.
* **Payment link** - a Razorpay payment page (``/v1/payment_links``) shown as a
  QR code and optionally sent by SMS. The customer can pay by UPI, card,
  net banking or wallet.

Only the Razorpay payment ID (``pay_...``) is stored with the sale. The API key
secret never leaves this module except as an HTTP Basic credential sent to
``api.razorpay.com`` over HTTPS.
"""
from __future__ import annotations

import base64
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable
from urllib.parse import urlencode, urlparse

from app.config.constants import APP_VERSION
from app.services.errors import BusinessError, ValidationError
from app.utils.money import money

API = "https://api.razorpay.com/v1"
KEY_ID_RE = re.compile(r"^rzp_(test|live)_[A-Za-z0-9]{6,40}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9]{10,64}$")
PAYMENT_ID_RE = re.compile(r"^pay_[A-Za-z0-9]{6,40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_]{4,60}$")
QR_MINUTES = 20          # a QR closes itself after this long (if not paid or closed sooner)
LINK_MINUTES = 30        # payment links must live at least 15 minutes

# (method, url, headers, body, timeout) -> (HTTP status, response body)
Transport = Callable[[str, str, dict, "bytes | None", float], "tuple[int, bytes]"]


class RazorpayError(BusinessError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 network: bool = False):
        super().__init__(message)
        self.status, self.code, self.network = status, code, network


def tls_context() -> ssl.SSLContext:
    """Trust the Windows certificate store plus Mozilla's bundle (certifi), so HTTPS works
    even on a fresh Windows install that has not downloaded every root yet."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    return ctx


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None,
                     timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout,  # noqa: S310 - https only
                                    context=tls_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def paise(amount) -> int:
    return int(money(amount) * 100)


def rupees(amount_paise) -> Decimal:
    return money(Decimal(int(amount_paise)) / 100)


def validate_keys(key_id, key_secret) -> tuple[str, str]:
    key_id = ("" if key_id is None else str(key_id)).strip()
    key_secret = ("" if key_secret is None else str(key_secret)).strip()
    if not KEY_ID_RE.match(key_id):
        raise ValidationError("The Key ID looks like rzp_live_... or rzp_test_... "
                              "(Razorpay Dashboard › Account & Settings › API keys).")
    if not SECRET_RE.match(key_secret):
        raise ValidationError("Enter the Key Secret exactly as Razorpay showed it "
                              "(letters and digits only).")
    return key_id, key_secret


def _check_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise RazorpayError("Unexpected Razorpay ID.")
    return value


@dataclass(frozen=True)
class PaidResult:
    payment_id: str
    amount: Decimal
    method: str = ""          # upi / card / netbanking / wallet ...
    detail: str = ""          # e.g. the customer's UPI ID (vpa)

    @property
    def description(self) -> str:
        how = {"upi": "UPI", "card": "Card", "netbanking": "Net banking",
               "wallet": "Wallet"}.get(self.method, self.method.title() if self.method else "")
        return f"{how} via Razorpay" if how else "Razorpay"


class RazorpayClient:
    def __init__(self, key_id: str, key_secret: str, transport: Transport | None = None,
                 timeout: float = 15):
        self.key_id, self._secret = key_id, key_secret
        self.transport = transport or urllib_transport
        self.timeout = timeout

    @property
    def test_mode(self) -> bool:
        return self.key_id.startswith("rzp_test_")

    def _call(self, method: str, path: str, payload: dict | None = None,
              params: dict | None = None) -> dict:
        url = API + path + (("?" + urlencode(params)) if params else "")
        token = base64.b64encode(f"{self.key_id}:{self._secret}".encode()).decode("ascii")
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json",
                   "User-Agent": f"BusinessPOS/{APP_VERSION}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            status, raw = self.transport(method, url, headers, body, self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RazorpayError("Can't reach Razorpay. Check the internet connection and try "
                                "again.", network=True) from None
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}
        if 200 <= status < 300:
            return data if isinstance(data, dict) else {}
        err = data.get("error") if isinstance(data, dict) else None
        err = err if isinstance(err, dict) else {}
        if status == 401:
            raise RazorpayError("Razorpay did not accept the API Key ID / Key Secret. Check "
                                "them in the Razorpay Dashboard › Account & Settings › "
                                "API keys.", status=401, code=err.get("code"))
        if status >= 500:
            raise RazorpayError("Razorpay is having a problem right now. Try again in a "
                                "minute.", status=status, code=err.get("code"), network=True)
        raise RazorpayError(err.get("description") or f"Razorpay refused the request "
                            f"(HTTP {status}).", status=status, code=err.get("code"))

    # ---- account --------------------------------------------------------------------
    def verify(self) -> None:
        """Cheap authenticated call: raises RazorpayError when the keys are wrong."""
        self._call("GET", "/payments", params={"count": 1})

    # ---- UPI QR codes -----------------------------------------------------------------
    def create_upi_qr(self, amount, *, name: str, description: str,
                      notes: dict | None = None, close_by: int | None = None) -> dict:
        payload = {"type": "upi_qr", "name": name[:40] or "BusinessPOS", "usage": "single_use",
                   "fixed_amount": True, "payment_amount": paise(amount),
                   "description": description[:100], "notes": notes or {}}
        if close_by:
            payload["close_by"] = close_by
        try:
            return self._call("POST", "/payments/qr_codes", payload)
        except RazorpayError as exc:
            if close_by and exc.status == 400 and "close_by" in str(exc):
                return self.create_upi_qr(amount, name=name, description=description,
                                          notes=notes)   # PC clock is off: no auto-close
            raise

    def qr_payments(self, qr_id: str) -> list[dict]:
        items = self._call("GET", f"/payments/qr_codes/{_check_id(qr_id)}/payments").get("items")
        return items if isinstance(items, list) else []

    def close_qr(self, qr_id: str) -> dict:
        return self._call("POST", f"/payments/qr_codes/{_check_id(qr_id)}/close", {})

    # ---- payment links ----------------------------------------------------------------
    def create_payment_link(self, amount, *, description: str, contact: str = "",
                            name: str = "", notes: dict | None = None,
                            expire_by: int | None = None) -> dict:
        payload = {"amount": paise(amount), "currency": "INR", "accept_partial": False,
                   "description": description[:2048], "reminder_enable": False,
                   "notes": notes or {}, "notify": {"sms": bool(contact), "email": False}}
        customer = {k: v for k, v in (("name", name.strip()[:100]), ("contact", contact))
                    if v}
        if customer:
            payload["customer"] = customer
        if expire_by:
            payload["expire_by"] = expire_by
        try:
            return self._call("POST", "/payment_links", payload)
        except RazorpayError as exc:
            if expire_by and exc.status == 400 and "expire" in str(exc).lower():
                return self.create_payment_link(amount, description=description,
                                                contact=contact, name=name, notes=notes)
            raise

    def get_payment_link(self, link_id: str) -> dict:
        return self._call("GET", f"/payment_links/{_check_id(link_id)}")

    def cancel_payment_link(self, link_id: str) -> dict:
        return self._call("POST", f"/payment_links/{_check_id(link_id)}/cancel", {})

    # ---- payments ---------------------------------------------------------------------
    def get_payment(self, payment_id: str) -> dict:
        return self._call("GET", f"/payments/{_check_id(payment_id)}")

    def list_payments(self, start: datetime, end: datetime, limit: int = 2000) -> list[dict]:
        out: list[dict] = []
        while len(out) < limit:
            page = self._call("GET", "/payments", params={
                "from": int(start.timestamp()), "to": int(end.timestamp()) - 1,
                "count": 100, "skip": len(out)}).get("items") or []
            out.extend(p for p in page if isinstance(p, dict))
            if len(page) < 100:
                break
        return out

    def fetch_image(self, url: str, max_bytes: int = 2_000_000) -> bytes:
        """Download the QR image Razorpay hosts (no credentials are sent)."""
        if urlparse(url or "").scheme != "https":
            raise RazorpayError("Razorpay returned an unexpected QR image address.")
        try:
            status, raw = self.transport("GET", url, {"User-Agent": f"BusinessPOS/{APP_VERSION}"},
                                         None, self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RazorpayError("Can't download the QR image. Check the internet connection.",
                                network=True) from None
        if status != 200 or not raw or len(raw) > max_bytes:
            raise RazorpayError("Can't download the QR image from Razorpay.")
        return raw


def _captured(p: dict, expected_paise: int) -> PaidResult | None:
    pid = p.get("id") or p.get("payment_id") or ""
    if p.get("status") == "captured" and int(p.get("amount") or 0) == expected_paise \
            and PAYMENT_ID_RE.match(pid):
        return PaidResult(pid, rupees(p["amount"]), str(p.get("method") or ""),
                          str(p.get("vpa") or ""))
    return None


class Collection:
    """One attempt to collect ``amount``: start, check (poll), cancel."""

    kind = ""

    def __init__(self, client: RazorpayClient, amount, *, shop: str, note: str):
        self.client, self.amount = client, money(amount)
        if self.amount <= 0:
            raise ValidationError("The amount to collect must be greater than zero.")
        self.shop, self.note = shop or "Shop", note
        self.id: str | None = None
        self.data: dict = {}

    @property
    def expected(self) -> int:
        return paise(self.amount)

    def notes(self) -> dict:
        return {"source": "BusinessPOS", "note": self.note[:200]}

    def start(self) -> dict:
        raise NotImplementedError

    def check(self) -> PaidResult | None:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    def cancel(self) -> PaidResult | None:
        """Stop accepting payment, then look once more: a payment that arrived at the last
        moment is returned so it is recorded, never lost."""
        if not self.id:
            return None
        try:
            self._close()
        except RazorpayError as exc:
            if exc.network:
                raise
        return self.check()


class QrCollection(Collection):
    kind = "qr"

    def start(self) -> dict:
        self.data = self.client.create_upi_qr(
            self.amount, name=self.shop, description=self.note, notes=self.notes(),
            close_by=int(time.time()) + QR_MINUTES * 60)
        self.id = _check_id(self.data.get("id", ""))
        return self.data

    def check(self) -> PaidResult | None:
        for p in self.client.qr_payments(self.id):
            paid = _captured(p, self.expected)
            if paid:
                return paid
        return None

    def _close(self) -> None:
        self.client.close_qr(self.id)


class LinkCollection(Collection):
    kind = "link"

    def __init__(self, client, amount, *, shop: str, note: str, contact: str = "",
                 customer: str = ""):
        super().__init__(client, amount, shop=shop, note=note)
        digits = re.sub(r"\D", "", contact or "")
        if contact and not 10 <= len(digits) <= 13:
            raise ValidationError("Enter the customer's 10-digit mobile number, or leave it "
                                  "blank.")
        self.contact = ("+91" + digits[-10:]) if digits else ""
        self.customer = customer

    def start(self) -> dict:
        self.data = self.client.create_payment_link(
            self.amount, description=f"{self.shop}: {self.note}", contact=self.contact,
            name=self.customer, notes=self.notes(),
            expire_by=int(time.time()) + LINK_MINUTES * 60)
        self.id = _check_id(self.data.get("id", ""))
        if urlparse(self.data.get("short_url") or "").scheme != "https":
            raise RazorpayError("Razorpay did not return a payment link.")
        return self.data

    def check(self) -> PaidResult | None:
        link = self.client.get_payment_link(self.id)
        if link.get("status") != "paid":
            return None
        for p in link.get("payments") or []:
            paid = _captured({**p, "id": p.get("payment_id")}, self.expected)
            if paid:
                return paid
        return None

    def _close(self) -> None:
        self.client.cancel_payment_link(self.id)
