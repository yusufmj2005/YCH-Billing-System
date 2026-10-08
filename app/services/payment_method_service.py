"""Configurable payment methods (record-keeping only; no gateway processing)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.config.constants import PaymentKind, Perm
from app.database.database import Database
from app.models import PaymentMethod
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.validators import common as v


def method_dict(m: PaymentMethod) -> dict:
    return {"id": m.id, "kind": m.kind, "name": m.name, "allows_reference": m.allows_reference,
            "requires_description": m.requires_description, "is_active": m.is_active,
            "is_system": m.is_system, "sort_order": m.sort_order}


class PaymentMethodService:
    def __init__(self, db: Database):
        self.db = db

    def list(self, include_inactive: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(PaymentMethod).order_by(PaymentMethod.sort_order, PaymentMethod.id)
            if not include_inactive:
                q = q.where(PaymentMethod.is_active.is_(True))
            return [method_dict(m) for m in s.scalars(q)]

    def save(self, actor: CurrentUser, method_id: int | None, data: dict) -> int:
        require(actor, Perm.MANAGE_SETTINGS)
        name = v.text(data.get("name"), "Payment method name", required=True, max_len=64)
        with self.db.session() as s:
            dup = s.scalar(select(PaymentMethod.id).where(PaymentMethod.name == name))
            if dup and dup != method_id:
                raise ValidationError("A payment method with this name already exists.")
            if method_id is None:
                order = (s.scalar(select(func.max(PaymentMethod.sort_order))) or 0) + 1
                m = PaymentMethod(kind=PaymentKind.CUSTOM, name=name, sort_order=order)
                s.add(m)
                action = "PAYMENT_METHOD_CREATED"
            else:
                m = s.get(PaymentMethod, method_id)
                if m is None:
                    raise NotFound("Payment method not found.")
                action = "PAYMENT_METHOD_UPDATED"
            m.name = name
            if m.kind == PaymentKind.RAZORPAY:
                m.allows_reference = True          # holds the Razorpay payment ID
            elif m.kind != PaymentKind.CASH:
                m.allows_reference = bool(data.get("allows_reference", m.allows_reference))
            m.requires_description = bool(data.get("requires_description", m.requires_description)) \
                if m.kind in (PaymentKind.OTHER, PaymentKind.CUSTOM) else m.requires_description
            if "is_active" in data:
                m.is_active = bool(data["is_active"])
            s.flush()
            if not s.scalar(select(func.count(PaymentMethod.id))
                            .where(PaymentMethod.is_active.is_(True))):
                raise ValidationError("At least one payment method must remain enabled.")
            audit_service.record(s, actor, action, "payment_method", m.id,
                                 {"name": m.name, "active": m.is_active})
            return m.id
