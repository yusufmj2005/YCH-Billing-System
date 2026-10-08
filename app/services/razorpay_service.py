"""Razorpay connection, payment checks and daily reconciliation."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select

from app.config.constants import PaymentDirection, PaymentKind, Perm
from app.database.database import Database
from app.models import Payment, PaymentMethod, Sale, Setting
from app.payments.razorpay import (PAYMENT_ID_RE, PaidResult, RazorpayClient, RazorpayError,
                                   Transport, paise, rupees, validate_keys)
from app.security import secret_store
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import BusinessError, ValidationError
from app.utils.dates import day_end_exclusive, day_start
from app.utils.money import money

KEY_ID = "razorpay_key_id"
SECRET = "secret_razorpay_key_secret"
METHOD_NAME = "Razorpay"


class NotConnected(BusinessError):
    def __init__(self, message: str = "Razorpay is not connected. An administrator can "
                                      "connect it in Settings › Payments."):
        super().__init__(message)


class RazorpayService:
    def __init__(self, db: Database, transport: Transport | None = None):
        self.db = db
        self.transport = transport          # tests inject a fake Razorpay

    # ---- stored keys --------------------------------------------------------------
    def _rows(self) -> tuple[str, str | None]:
        with self.db.session() as s:
            kid, sec = s.get(Setting, KEY_ID), s.get(Setting, SECRET)
            key_id = json.loads(kid.value) if kid else ""
            return key_id or "", (json.loads(sec.value) if sec else None)

    def status(self) -> dict:
        key_id, stored = self._rows()
        ok = False
        if key_id and stored:
            try:
                secret_store.unprotect(stored)
                ok = True
            except secret_store.SecretUnavailable:
                ok = False
        return {"connected": bool(key_id and ok), "key_id": key_id,
                "needs_secret": bool(key_id and not ok),
                "mode": "test" if key_id.startswith("rzp_test_") else "live" if key_id else ""}

    def client(self) -> RazorpayClient:
        key_id, stored = self._rows()
        if not key_id or not stored:
            raise NotConnected()
        try:
            secret = secret_store.unprotect(stored)
        except secret_store.SecretUnavailable:
            raise NotConnected("Razorpay needs its Key Secret again on this computer (it "
                               "is locked to the Windows account that saved it). An "
                               "administrator can re-enter it in Settings › Payments.") from None
        return RazorpayClient(key_id, secret, transport=self.transport)

    def method(self) -> dict | None:
        from app.services.payment_method_service import method_dict
        with self.db.session() as s:
            m = s.scalar(select(PaymentMethod).where(PaymentMethod.kind == PaymentKind.RAZORPAY))
            return method_dict(m) if m else None

    def connect(self, actor: CurrentUser, key_id, key_secret) -> dict:
        """Check the keys with Razorpay, then save them and enable the Razorpay method."""
        require(actor, Perm.MANAGE_SETTINGS)
        key_id, key_secret = validate_keys(key_id, key_secret)
        RazorpayClient(key_id, key_secret, transport=self.transport).verify()
        protected = secret_store.protect(key_secret)
        with self.db.session() as s:
            for key, value in ((KEY_ID, key_id), (SECRET, protected)):
                row = s.get(Setting, key)
                if row is None:
                    s.add(Setting(key=key, value=json.dumps(value), updated_by=actor.id))
                else:
                    row.value, row.updated_by = json.dumps(value), actor.id
            m = s.scalar(select(PaymentMethod).where(PaymentMethod.kind == PaymentKind.RAZORPAY))
            if m is None:     # adopt a "Razorpay" method the shop already created by hand
                m = s.scalar(select(PaymentMethod).where(PaymentMethod.name == METHOD_NAME))
            if m is None:
                order = max((x.sort_order for x in s.scalars(select(PaymentMethod))), default=0)
                m = PaymentMethod(name=METHOD_NAME, sort_order=order + 1, is_system=True)
                s.add(m)
            m.kind, m.allows_reference, m.requires_description = PaymentKind.RAZORPAY, True, False
            m.is_active = True
            s.flush()
            audit_service.record(s, actor, "RAZORPAY_CONNECTED", "payment_method", m.id,
                                 {"key_id": key_id})
        return self.status()

    def disconnect(self, actor: CurrentUser) -> None:
        require(actor, Perm.MANAGE_SETTINGS)
        with self.db.session() as s:
            for key in (KEY_ID, SECRET):
                row = s.get(Setting, key)
                if row is not None:
                    s.delete(row)
            m = s.scalar(select(PaymentMethod).where(PaymentMethod.kind == PaymentKind.RAZORPAY))
            if m is not None:
                m.is_active = False     # kept: past sales still refer to it
            audit_service.record(s, actor, "RAZORPAY_DISCONNECTED", "payment_method",
                                 m.id if m else None)

    # ---- payments -----------------------------------------------------------------
    def used_on(self, payment_id: str) -> str | None:
        """Invoice number of the (non-void) sale that already recorded this payment."""
        with self.db.session() as s:
            return s.scalar(select(Sale.invoice_no).join(Payment, Payment.sale_id == Sale.id)
                            .where(Payment.reference == payment_id,
                                   Payment.direction == PaymentDirection.IN,
                                   Payment.is_void.is_(False)))

    def existing_payment(self, actor: CurrentUser, payment_id, amount) -> PaidResult:
        """Accept a payment the customer already made (e.g. the app was closed while they
        paid): it must be captured, for exactly ``amount``, and not used on another sale."""
        require(actor, Perm.CREATE_SALE)
        pid = ("" if payment_id is None else str(payment_id)).strip()
        if not PAYMENT_ID_RE.match(pid):
            raise ValidationError("Enter the Razorpay payment ID, e.g. pay_O8x1AbCdEfGh12.")
        inv = self.used_on(pid)
        if inv:
            raise ValidationError(f"Payment {pid} is already recorded on invoice {inv}.")
        try:
            p = self.client().get_payment(pid)
        except RazorpayError as exc:
            if exc.status in (400, 404):
                raise ValidationError(f"Razorpay has no payment {pid} on this account.") from None
            raise
        if p.get("status") != "captured":
            raise ValidationError(f"Payment {pid} is “{p.get('status') or 'unknown'}” at "
                                  "Razorpay, not captured. Only completed payments can be used.")
        if int(p.get("amount_refunded") or 0):
            raise ValidationError(f"Payment {pid} has been refunded at Razorpay.")
        if int(p.get("amount") or 0) != paise(amount):
            raise ValidationError(f"Payment {pid} is for ₹{rupees(p.get('amount') or 0)}, "
                                  f"not ₹{money(amount)}.")
        return PaidResult(pid, rupees(p["amount"]), str(p.get("method") or ""),
                          str(p.get("vpa") or ""))

    def reconcile(self, actor: CurrentUser, day: date) -> dict:
        """Razorpay's payments for ``day`` side by side with the sales that recorded them."""
        require(actor, Perm.VIEW_REPORTS)
        start, end = day_start(day), day_end_exclusive(day)
        remote = self.client().list_payments(start, end)
        with self.db.session() as s:
            local = s.execute(
                select(Payment.reference, Payment.amount, Sale.invoice_no, Sale.status,
                       Payment.is_void)
                .join(Sale, Payment.sale_id == Sale.id)
                .join(PaymentMethod, Payment.payment_method_id == PaymentMethod.id)
                .where(Payment.direction == PaymentDirection.IN,
                       PaymentMethod.kind == PaymentKind.RAZORPAY,
                       Payment.created_at >= start, Payment.created_at < end)).all()
            refs = {p.get("id") for p in remote}
            recorded = {}
            for pid in refs:
                row = s.execute(select(Sale.invoice_no, Payment.is_void)
                                .join(Payment, Payment.sale_id == Sale.id)
                                .where(Payment.reference == pid,
                                       Payment.direction == PaymentDirection.IN)
                                .order_by(Payment.is_void)).first()
                if row:
                    recorded[pid] = row
        rows, missing, captured_total = [], 0, money(0)
        for p in sorted(remote, key=lambda x: x.get("created_at") or 0):
            pid, status = p.get("id") or "", p.get("status") or ""
            amount = rupees(p.get("amount") or 0)
            if status == "captured":
                captured_total += amount
            rec = recorded.get(pid)
            if rec:
                note = f"Invoice {rec[0]}" + (" (voided: refund at Razorpay)" if rec[1] else "")
            elif status == "captured":
                note = "NOT RECORDED in BusinessPOS"
                missing += 1
            else:
                note = "-"
            rows.append({"time": datetime.fromtimestamp(int(p.get("created_at") or 0)),
                         "payment_id": pid, "method": str(p.get("method") or "").upper(),
                         "amount": amount, "status": status.title(),
                         "refunded": rupees(p.get("amount_refunded") or 0), "invoice": note})
        unknown = [r for r in local if r.reference not in refs and not r.is_void]
        for r in unknown:
            rows.append({"time": None, "payment_id": r.reference or "", "method": "",
                         "amount": r.amount, "status": "Not found at Razorpay",
                         "refunded": money(0), "invoice": f"Invoice {r.invoice_no}"})
        recorded_total = sum((r.amount for r in local if not r.is_void), money(0))
        return {"rows": rows, "captured_total": captured_total,
                "recorded_total": recorded_total, "not_recorded": missing,
                "unknown": len(unknown)}
