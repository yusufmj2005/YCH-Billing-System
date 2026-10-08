"""Purchases from suppliers.

Draft  -> editable, no stock effect.
Complete -> stock increases (PURCHASE movements), optional cost price update.
Cancel (completed) -> stock reversed (PURCHASE_CANCEL movements), payments voided.
Supplier payments are recorded as outgoing ``payments`` linked to the purchase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.constants import (MovementType, PaymentDirection, PaymentStatus, Perm,
                                  PurchaseStatus)
from app.database.database import Database
from app.models import Payment, PaymentMethod, Product, Purchase, PurchaseItem, Supplier
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.services.inventory_service import apply_movement
from app.services.sales_service import clean_reference
from app.services.settings_service import format_doc_no, get_settings, next_sequence
from app.utils.dates import now
from app.utils.money import ZERO, fmt_money, money
from app.validators import common as v


@dataclass
class PurchaseLineRequest:
    product_id: int
    quantity: Decimal
    unit_cost: Decimal
    discount_amount: Decimal = ZERO
    tax_rate: Decimal = ZERO


@dataclass
class PurchaseRequest:
    supplier_id: int
    purchase_date: date
    lines: list[PurchaseLineRequest]
    supplier_invoice_no: str | None = None
    notes: str | None = None
    update_cost_prices: bool = True


def compute_purchase_line(q: Decimal, unit_cost: Decimal, discount: Decimal, rate: Decimal):
    gross = money(unit_cost * q)
    discount = money(discount)
    if discount < 0 or discount > gross:
        raise ValidationError("Purchase line discount must be between 0 and the line amount.")
    taxable = gross - discount
    tax = money(taxable * rate / 100)
    return gross, discount, taxable, tax, taxable + tax


def _payment_status(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return PaymentStatus.UNPAID if total > 0 else PaymentStatus.PAID
    return PaymentStatus.PAID if paid >= total else PaymentStatus.PARTIAL


class PurchaseService:
    def __init__(self, db: Database):
        self.db = db

    def _fill(self, s: Session, p: Purchase, req: PurchaseRequest) -> None:
        sup = s.get(Supplier, req.supplier_id)
        if sup is None:
            raise ValidationError("Please select a supplier.")
        if not req.lines:
            raise ValidationError("Add at least one product to the purchase.")
        p.supplier_id = sup.id
        p.purchase_date = v.as_date(req.purchase_date, "Purchase date")
        p.supplier_invoice_no = v.text(req.supplier_invoice_no, "Supplier invoice / reference",
                                       max_len=64)
        p.notes = v.text(req.notes, "Notes", max_len=2000)
        p.update_cost_prices = bool(req.update_cost_prices)
        for old in list(p.items):
            p.items.remove(old)
        s.flush()
        subtotal = disc_total = tax_total = grand = ZERO
        for ln in req.lines:
            prod = s.get(Product, ln.product_id)
            if prod is None:
                raise ValidationError("A product on this purchase no longer exists.")
            q = v.quantity(ln.quantity, f"Quantity of {prod.name}",
                           allow_fraction=prod.allow_fractional_qty)
            cost = v.amount(ln.unit_cost, f"Unit cost of {prod.name}")
            rate = v.percent(ln.tax_rate or 0, "Tax rate")
            gross, disc, taxable, tax, total = compute_purchase_line(
                q, cost, ln.discount_amount or ZERO, rate)
            p.items.append(PurchaseItem(product_id=prod.id, product_name=prod.name, quantity=q,
                                        unit_cost=cost, gross_amount=gross, discount_amount=disc,
                                        taxable_amount=taxable, tax_rate=rate, tax_amount=tax,
                                        line_total=total))
            subtotal += gross
            disc_total += disc
            tax_total += tax
            grand += total
        p.subtotal, p.discount_total, p.tax_total, p.grand_total = subtotal, disc_total, tax_total, grand
        p.payment_status = _payment_status(grand, p.amount_paid or ZERO)

    def save_draft(self, actor: CurrentUser, purchase_id: int | None, req: PurchaseRequest,
                   complete: bool = False) -> dict:
        require(actor, Perm.CREATE_PURCHASE)
        with self.db.session() as s:
            if purchase_id is None:
                settings = get_settings(s)
                number = next_sequence(s, "purchase")
                p = Purchase(purchase_no=format_doc_no(settings.get("purchase_prefix") or "",
                                                       number, 6),
                             status=PurchaseStatus.DRAFT, created_by=actor.id,
                             subtotal=ZERO, discount_total=ZERO, tax_total=ZERO,
                             grand_total=ZERO, amount_paid=ZERO,
                             payment_status=PaymentStatus.UNPAID,
                             purchase_date=req.purchase_date, supplier_id=req.supplier_id)
                s.add(p)
                action = "PURCHASE_DRAFT_CREATED"
            else:
                p = s.get(Purchase, purchase_id)
                if p is None:
                    raise NotFound("Purchase not found.")
                if p.status != PurchaseStatus.DRAFT:
                    raise ValidationError("Only draft purchases can be edited.")
                action = "PURCHASE_DRAFT_UPDATED"
            self._fill(s, p, req)
            s.flush()
            audit_service.record(s, actor, action, "purchase", p.id,
                                 {"purchase_no": p.purchase_no, "total": str(p.grand_total)})
            if complete:
                self._complete(s, actor, p)
            return {"purchase_id": p.id, "purchase_no": p.purchase_no}

    def _complete(self, s: Session, actor: CurrentUser, p: Purchase) -> None:
        if p.status != PurchaseStatus.DRAFT:
            raise ValidationError("Only draft purchases can be completed.")
        for item in p.items:
            prod = s.get(Product, item.product_id)
            unit_net = money(item.taxable_amount / item.quantity)
            apply_movement(s, actor, prod, item.quantity, MovementType.PURCHASE,
                           reference_type="PURCHASE", reference_id=p.id,
                           reference_no=p.purchase_no, unit_cost=unit_net,
                           reason=f"Purchase from {p.supplier.name}"
                           + (f" (inv. {p.supplier_invoice_no})" if p.supplier_invoice_no else ""))
            if p.update_cost_prices and prod.purchase_price != unit_net:
                audit_service.record(s, actor, "PRODUCT_COST_UPDATED", "product", prod.id, {
                    "name": prod.name, "from": str(prod.purchase_price), "to": str(unit_net),
                    "purchase_no": p.purchase_no})
                prod.purchase_price = unit_net
        p.status = PurchaseStatus.COMPLETED
        p.completed_at = now()
        p.completed_by = actor.id
        audit_service.record(s, actor, "PURCHASE_COMPLETED", "purchase", p.id,
                             {"purchase_no": p.purchase_no, "supplier": p.supplier.name,
                              "total": str(p.grand_total)})

    def complete(self, actor: CurrentUser, purchase_id: int) -> None:
        require(actor, Perm.CREATE_PURCHASE)
        with self.db.session() as s:
            p = s.get(Purchase, purchase_id)
            if p is None:
                raise NotFound("Purchase not found.")
            self._complete(s, actor, p)

    def discard_draft(self, actor: CurrentUser, purchase_id: int) -> None:
        require(actor, Perm.CREATE_PURCHASE)
        with self.db.session() as s:
            p = s.get(Purchase, purchase_id)
            if p is None:
                raise NotFound("Purchase not found.")
            if p.status != PurchaseStatus.DRAFT:
                raise ValidationError("Only drafts can be discarded. Cancel completed purchases.")
            no = p.purchase_no
            s.delete(p)
            audit_service.record(s, actor, "PURCHASE_DRAFT_DISCARDED", "purchase", purchase_id,
                                 {"purchase_no": no})

    def cancel(self, actor: CurrentUser, purchase_id: int, reason: str) -> None:
        require(actor, Perm.CANCEL_PURCHASE)
        reason = v.text(reason, "Reason", required=True, max_len=500)
        with self.db.session() as s:
            p = s.get(Purchase, purchase_id)
            if p is None:
                raise NotFound("Purchase not found.")
            if p.status != PurchaseStatus.COMPLETED:
                raise ValidationError("Only completed purchases can be cancelled.")
            allow_negative = bool(get_settings(s).get("allow_negative_stock"))
            for item in p.items:
                prod = s.get(Product, item.product_id)
                apply_movement(s, actor, prod, -item.quantity, MovementType.PURCHASE_CANCEL,
                               reference_type="PURCHASE", reference_id=p.id,
                               reference_no=p.purchase_no, reason=f"Purchase cancelled: {reason}",
                               allow_negative=allow_negative)
            for pay in s.scalars(select(Payment).where(Payment.purchase_id == p.id)):
                pay.is_void = True
            p.status = PurchaseStatus.CANCELLED
            p.cancelled_at = now()
            p.cancelled_by = actor.id
            p.cancel_reason = reason
            audit_service.record(s, actor, "PURCHASE_CANCELLED", "purchase", p.id,
                                 {"purchase_no": p.purchase_no, "reason": reason})

    def record_payment(self, actor: CurrentUser, purchase_id: int, payment_method_id: int,
                       amount, reference: str | None = None,
                       description: str | None = None) -> None:
        require(actor, Perm.CREATE_PURCHASE)
        with self.db.session() as s:
            p = s.get(Purchase, purchase_id)
            if p is None:
                raise NotFound("Purchase not found.")
            if p.status != PurchaseStatus.COMPLETED:
                raise ValidationError("Payments can only be recorded for completed purchases.")
            method = s.get(PaymentMethod, payment_method_id)
            if method is None or not method.is_active:
                raise ValidationError("Selected payment method is not available.")
            amt = v.amount(amount, "Amount", positive=True)
            balance = p.grand_total - p.amount_paid
            if amt > balance:
                raise ValidationError(f"Amount exceeds the balance due ({fmt_money(balance)}).")
            desc = v.text(description, "Description", max_len=200)
            if method.requires_description and not desc:
                raise ValidationError("Please describe the payment method.")
            s.add(Payment(direction=PaymentDirection.OUT, purchase_id=p.id,
                          payment_method_id=method.id, method_name=method.name, amount=amt,
                          reference=clean_reference(reference) if method.allows_reference else None,
                          description=desc, user_id=actor.id))
            p.amount_paid = p.amount_paid + amt
            p.payment_status = _payment_status(p.grand_total, p.amount_paid)
            audit_service.record(s, actor, "PURCHASE_PAYMENT", "purchase", p.id,
                                 {"purchase_no": p.purchase_no, "method": method.name,
                                  "amount": str(amt)})

    def list_purchases(self, actor: CurrentUser, *, date_from: date | None = None,
                       date_to: date | None = None, supplier_id: int | None = None,
                       status: str | None = None, search: str = "", limit: int = 200,
                       offset: int = 0) -> tuple[list[dict], int]:
        require(actor, Perm.VIEW_PURCHASES)
        with self.db.session() as s:
            q = select(Purchase).join(Supplier)
            if date_from:
                q = q.where(Purchase.purchase_date >= date_from)
            if date_to:
                q = q.where(Purchase.purchase_date <= date_to)
            if supplier_id:
                q = q.where(Purchase.supplier_id == supplier_id)
            if status:
                q = q.where(Purchase.status == status)
            if search:
                like = f"%{search.strip()}%"
                q = q.where(or_(Purchase.purchase_no.ilike(like),
                                Purchase.supplier_invoice_no.ilike(like),
                                Supplier.name.ilike(like)))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
                             .limit(limit).offset(offset)).all()
            return [{
                "id": p.id, "purchase_no": p.purchase_no, "purchase_date": p.purchase_date,
                "supplier": p.supplier.name, "supplier_invoice_no": p.supplier_invoice_no or "",
                "status": p.status, "items": len(p.items), "grand_total": p.grand_total,
                "amount_paid": p.amount_paid, "balance": p.grand_total - p.amount_paid,
                "payment_status": p.payment_status,
            } for p in rows], total

    def get_purchase(self, actor: CurrentUser, purchase_id: int) -> dict:
        require(actor, Perm.VIEW_PURCHASES)
        with self.db.session() as s:
            p = s.get(Purchase, purchase_id)
            if p is None:
                raise NotFound("Purchase not found.")
            return {
                "id": p.id, "purchase_no": p.purchase_no, "purchase_date": p.purchase_date,
                "supplier_id": p.supplier_id, "supplier": p.supplier.name,
                "supplier_invoice_no": p.supplier_invoice_no or "", "status": p.status,
                "notes": p.notes or "", "update_cost_prices": p.update_cost_prices,
                "subtotal": p.subtotal, "discount_total": p.discount_total,
                "tax_total": p.tax_total, "grand_total": p.grand_total,
                "amount_paid": p.amount_paid, "payment_status": p.payment_status,
                "cancel_reason": p.cancel_reason or "",
                "items": [{"product_id": i.product_id, "product_name": i.product_name,
                           "quantity": i.quantity, "unit_cost": i.unit_cost,
                           "discount_amount": i.discount_amount, "tax_rate": i.tax_rate,
                           "taxable_amount": i.taxable_amount, "tax_amount": i.tax_amount,
                           "line_total": i.line_total} for i in p.items],
                "payments": [{"method": x.method_name, "amount": x.amount,
                              "reference": x.reference or "", "created_at": x.created_at,
                              "is_void": x.is_void} for x in p.payments],
            }
