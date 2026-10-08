"""POS sales: atomic checkout, voiding, queries.

``create_sale`` runs in ONE database transaction:
    validate cart -> validate stock -> compute totals -> validate payments
    -> allocate invoice number -> insert sale, items, payments
    -> reduce stock + write inventory movements -> audit -> COMMIT
Any exception rolls everything back; no partial sale can exist.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.config.constants import MovementType, PaymentDirection, Perm, SaleStatus, TaxMode
from app.database.database import Database
from app.models import (Customer, Payment, PaymentMethod, Product, ReturnItem, Sale, SaleItem,
                        SaleReturn)
from app.security.auth import CurrentUser, require, require_any
from app.services import audit_service
from app.services.errors import (BusinessError, InsufficientStock, NotFound, PermissionDenied,
                                 ValidationError)
from app.services.inventory_service import apply_movement
from app.services.pricing import CartLineInput, compute_cart
from app.services.settings_service import format_doc_no, get_settings, next_sequence
from app.utils.dates import day_end_exclusive, day_start, now
from app.utils.money import ZERO, fmt_money, fmt_qty, money
from app.validators import common as v

log = logging.getLogger(__name__)


@dataclass
class SaleLineRequest:
    product_id: int
    quantity: Decimal
    discount_amount: Decimal = ZERO
    discount_percent: Decimal | None = None


@dataclass
class PaymentRequest:
    payment_method_id: int
    amount: Decimal
    reference: str | None = None
    description: str | None = None


@dataclass
class SaleRequest:
    lines: list[SaleLineRequest]
    payments: list[PaymentRequest] = field(default_factory=list)
    customer_id: int | None = None
    bill_discount_amount: Decimal = ZERO
    bill_discount_percent: Decimal | None = None
    tax_mode: str | None = None
    notes: str | None = None


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def clean_reference(ref: str | None) -> str | None:
    """Validate an optional transaction / reference id. Rejects values that
    look like a full payment card number (we never store card numbers)."""
    ref = v.text(ref, "Reference ID", max_len=100)
    if ref:
        compact = ref.replace(" ", "").replace("-", "")
        if compact.isdigit() and 13 <= len(compact) <= 19 and _luhn_ok(compact):
            raise ValidationError(
                "This looks like a card number. Enter only the transaction / reference ID "
                "from the terminal slip - never the card number.")
    return ref


def validate_payments(s: Session, payments: list[PaymentRequest], expected_total: Decimal,
                      *, label: str = "invoice total") -> list[tuple[PaymentMethod, Decimal,
                                                                     str | None, str | None]]:
    out = []
    for p in payments:
        method = s.get(PaymentMethod, p.payment_method_id)
        if method is None or not method.is_active:
            raise ValidationError("Selected payment method is not available.")
        amount = v.decimal(p.amount, f"{method.name} amount", min_value=0)
        if amount <= 0:
            raise ValidationError("Payment amounts must be greater than zero.")
        reference = clean_reference(p.reference) if method.allows_reference else None
        description = v.text(p.description, "Payment description", max_len=200)
        if method.requires_description and not description:
            raise ValidationError(f"Please describe the payment method for “{method.name}”.")
        out.append((method, amount, reference, description))
    paid = sum((a for _, a, _, _ in out), ZERO)
    if paid != expected_total:
        raise ValidationError(
            f"Payment total ({fmt_money(paid)}) does not match the {label} "
            f"({fmt_money(expected_total)}).")
    return out


class SalesService:
    def __init__(self, db: Database):
        self.db = db

    # ---- checkout --------------------------------------------------------------
    def build_cart(self, s: Session, req: SaleRequest, settings: dict):
        if not req.lines:
            raise ValidationError("The cart is empty.")
        products: dict[int, Product] = {}
        inputs: list[CartLineInput] = []
        for line in req.lines:
            p = products.get(line.product_id) or s.get(Product, line.product_id)
            if p is None:
                raise NotFound("A product in the cart no longer exists.")
            if not p.is_active:
                raise ValidationError(f"“{p.name}” is inactive and cannot be sold.")
            products[p.id] = p
            q = v.quantity(line.quantity, f"Quantity of {p.name}",
                           allow_fraction=p.allow_fractional_qty)
            inputs.append(CartLineInput(
                product_id=p.id, name=p.name, unit_price=p.selling_price, quantity=q,
                tax_rate=p.tax_rate.rate if p.tax_rate else ZERO,
                tax_rate_id=p.tax_rate_id, tax_name=p.tax_rate.name if p.tax_rate else "",
                price_includes_tax=p.price_includes_tax,
                discount_amount=money(line.discount_amount or ZERO),
                discount_percent=line.discount_percent))
        tax_mode = req.tax_mode or settings.get("default_tax_mode") or TaxMode.INTRA
        result = compute_cart(inputs, bill_discount_amount=money(req.bill_discount_amount or ZERO),
                              bill_discount_percent=req.bill_discount_percent, tax_mode=tax_mode,
                              round_off=bool(settings.get("round_off_total")))
        return products, inputs, result, tax_mode

    def _check_discount(self, actor: CurrentUser, result, settings: dict) -> None:
        if result.total_discount <= 0:
            return
        if not actor.has(Perm.APPLY_DISCOUNT):
            raise PermissionDenied("You do not have permission to apply discounts.")
        limit = settings.get("max_discount_percent")
        if limit not in (None, "") and not actor.has(Perm.OVERRIDE_DISCOUNT_LIMIT):
            if result.discount_percent_of_gross > Decimal(str(limit)):
                raise PermissionDenied(
                    f"Total discount ({result.discount_percent_of_gross}%) exceeds the allowed "
                    f"maximum of {limit}%. A manager must approve this discount.")

    def create_sale(self, actor: CurrentUser, req: SaleRequest) -> dict:
        require(actor, Perm.CREATE_SALE)
        with self.db.session() as s:
            settings = get_settings(s)
            products, inputs, result, tax_mode = self.build_cart(s, req, settings)
            self._check_discount(actor, result, settings)

            # Stock validation (aggregate quantities per product)
            needed: dict[int, Decimal] = {}
            for ln in inputs:
                needed[ln.product_id] = needed.get(ln.product_id, ZERO) + Decimal(ln.quantity)
            allow_negative = bool(settings.get("allow_negative_stock"))
            if not allow_negative:
                for pid, q in needed.items():
                    p = products[pid]
                    if q > p.current_stock:
                        raise InsufficientStock(
                            f"Insufficient stock for “{p.name}”. Available: "
                            f"{fmt_qty(p.current_stock)} {p.unit}, requested: {fmt_qty(q)}.")

            payments = validate_payments(s, req.payments, result.grand_total)

            customer = None
            if req.customer_id:
                customer = s.get(Customer, req.customer_id)
                if customer is None:
                    raise ValidationError("Selected customer not found.")

            number = next_sequence(s, "invoice")
            invoice_no = format_doc_no(settings.get("invoice_prefix") or "", number,
                                       settings.get("invoice_padding") or 6)
            if s.scalar(select(Sale.id).where(Sale.invoice_no == invoice_no)):
                raise BusinessError(
                    f"Invoice number {invoice_no} already exists. Please ask an administrator "
                    "to check the invoice numbering settings.")

            sale = Sale(
                invoice_no=invoice_no, invoice_number=number, created_at=now(), user_id=actor.id,
                customer_id=customer.id if customer else None,
                customer_name=customer.name if customer else None,
                customer_phone=customer.phone if customer else None,
                customer_gstin=customer.gstin if customer else None,
                customer_address=customer.address if customer else None,
                status=SaleStatus.COMPLETED, tax_mode=tax_mode,
                gross_total=result.gross_total, item_discount_total=result.item_discount_total,
                bill_discount=result.bill_discount,
                bill_discount_percent=req.bill_discount_percent,
                taxable_total=result.taxable_total, cgst_total=result.cgst_total,
                sgst_total=result.sgst_total, igst_total=result.igst_total,
                tax_total=result.tax_total, round_off=result.round_off,
                grand_total=result.grand_total, cost_total=ZERO,
                notes=v.text(req.notes, "Notes", max_len=1000),
            )
            s.add(sale)
            s.flush()

            cost_total = ZERO
            for ln, lr in zip(inputs, result.lines):
                p = products[ln.product_id]
                q = Decimal(ln.quantity)
                cost = money(p.purchase_price * q)
                cost_total += cost
                s.add(SaleItem(
                    sale_id=sale.id, product_id=p.id, product_name=p.name, sku=p.sku,
                    hsn_code=p.hsn_code, unit=p.unit, quantity=q, unit_price=ln.unit_price,
                    price_includes_tax=ln.price_includes_tax, gross_amount=lr.gross,
                    discount_amount=lr.discount, discount_percent=ln.discount_percent,
                    bill_discount_share=lr.bill_share, taxable_amount=lr.taxable,
                    tax_rate_id=ln.tax_rate_id, tax_name=ln.tax_name or None,
                    tax_rate=Decimal(ln.tax_rate), cgst_amount=lr.cgst, sgst_amount=lr.sgst,
                    igst_amount=lr.igst, tax_amount=lr.tax, line_total=lr.total,
                    unit_cost=p.purchase_price, cost_total=cost))
                apply_movement(s, actor, p, -q, MovementType.SALE, reference_type="SALE",
                               reference_id=sale.id, reference_no=invoice_no,
                               unit_cost=p.purchase_price, allow_negative=allow_negative)
            sale.cost_total = cost_total

            for method, amount, reference, description in payments:
                s.add(Payment(direction=PaymentDirection.IN, sale_id=sale.id,
                              payment_method_id=method.id, method_name=method.name,
                              amount=amount, reference=reference, description=description,
                              user_id=actor.id, created_at=sale.created_at))
            s.flush()
            audit_service.record(s, actor, "SALE_CREATED", "sale", sale.id, {
                "invoice_no": invoice_no, "total": str(result.grand_total),
                "items": len(inputs),
                "payments": [[m.name, str(a)] for m, a, _, _ in payments]})
            log.info("Sale %s completed (%s)", invoice_no, result.grand_total)
            return {"sale_id": sale.id, "invoice_no": invoice_no,
                    "grand_total": result.grand_total}

    # ---- void --------------------------------------------------------------------
    def void_sale(self, actor: CurrentUser, sale_id: int, reason: str) -> None:
        require(actor, Perm.CANCEL_SALE)
        reason = v.text(reason, "Reason", required=True, max_len=500)
        with self.db.session() as s:
            sale = s.get(Sale, sale_id)
            if sale is None:
                raise NotFound("Sale not found.")
            if sale.status != SaleStatus.COMPLETED:
                raise ValidationError("Only completed sales can be voided.")
            if s.scalar(select(SaleReturn.id).where(SaleReturn.sale_id == sale_id).limit(1)):
                raise ValidationError(
                    "This sale has returns recorded against it and cannot be voided.")
            for item in sale.items:
                p = s.get(Product, item.product_id)
                apply_movement(s, actor, p, item.quantity, MovementType.SALE_VOID,
                               reference_type="SALE", reference_id=sale.id,
                               reference_no=sale.invoice_no, reason=f"Sale voided: {reason}",
                               unit_cost=item.unit_cost, allow_negative=True)
            for pay in s.scalars(select(Payment).where(Payment.sale_id == sale_id)):
                pay.is_void = True
            sale.status = SaleStatus.VOIDED
            sale.voided_at = now()
            sale.voided_by = actor.id
            sale.void_reason = reason
            audit_service.record(s, actor, "SALE_VOIDED", "sale", sale.id,
                                 {"invoice_no": sale.invoice_no, "total": str(sale.grand_total),
                                  "reason": reason})

    # ---- queries -------------------------------------------------------------------
    def list_sales(self, actor: CurrentUser, *, date_from: date | None = None,
                   date_to: date | None = None, customer_id: int | None = None,
                   payment_method_id: int | None = None, status: str | None = None,
                   search: str = "", limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
        require_any(actor, Perm.VIEW_SALES, Perm.PROCESS_RETURN)
        with self.db.session() as s:
            q = select(Sale)
            if date_from:
                q = q.where(Sale.created_at >= day_start(date_from))
            if date_to:
                q = q.where(Sale.created_at < day_end_exclusive(date_to))
            if customer_id:
                q = q.where(Sale.customer_id == customer_id)
            if status:
                q = q.where(Sale.status == status)
            if payment_method_id:
                q = q.where(exists().where(Payment.sale_id == Sale.id,
                                           Payment.payment_method_id == payment_method_id))
            if search:
                like = f"%{search.strip()}%"
                q = q.where(or_(Sale.invoice_no.ilike(like), Sale.customer_name.ilike(like),
                                Sale.customer_phone.ilike(like)))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            sales = s.scalars(q.order_by(Sale.id.desc()).limit(limit).offset(offset)).all()
            ids = [x.id for x in sales]
            refunds = dict(s.execute(select(SaleReturn.sale_id, func.sum(SaleReturn.refund_total))
                                     .where(SaleReturn.sale_id.in_(ids))
                                     .group_by(SaleReturn.sale_id)).all()) if ids else {}
            rows = []
            for x in sales:
                methods = sorted({p.method_name for p in x.payments})
                rows.append({
                    "id": x.id, "invoice_no": x.invoice_no, "created_at": x.created_at,
                    "customer": x.customer_name or "Walk-in", "status": x.status,
                    "items": len(x.items), "taxable_total": x.taxable_total,
                    "tax_total": x.tax_total, "discount": x.item_discount_total + x.bill_discount,
                    "grand_total": x.grand_total, "refunded": refunds.get(x.id) or ZERO,
                    "payment_methods": ", ".join(methods),
                    "cashier": x.user.username if x.user else "",
                })
            return rows, total

    def find_invoices_for_return(self, actor: CurrentUser, *, product: str = "",
                                 customer: str = "", days: int = 90,
                                 limit: int = 50) -> list[dict]:
        """Invoices a customer may be returning goods from when the receipt is lost:
        completed sales in the last ``days`` days matching a product (name, SKU or
        barcode) and/or a customer (name or phone), with something still returnable."""
        require(actor, Perm.PROCESS_RETURN)
        product, customer = (product or "").strip(), (customer or "").strip()
        if not product and not customer:
            raise ValidationError("Enter a product or a customer to search for.")
        since = day_start(date.today()) - timedelta(days=max(1, int(days)))
        with self.db.session() as s:
            q = (select(Sale).where(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= since)
                 .order_by(Sale.id.desc()))
            if customer:
                like = f"%{customer}%"
                q = q.where(or_(Sale.customer_name.ilike(like), Sale.customer_phone.ilike(like)))
            if product:
                like = f"%{product}%"
                q = q.where(exists().where(
                    SaleItem.sale_id == Sale.id,
                    or_(SaleItem.product_name.ilike(like), SaleItem.sku.ilike(like),
                        SaleItem.product_id.in_(select(Product.id).where(
                            Product.barcode == product)))))
            out = []
            for sale in s.scalars(q.limit(limit * 3)):
                returned = dict(s.execute(
                    select(ReturnItem.sale_item_id, func.sum(ReturnItem.quantity))
                    .join(SaleReturn).where(SaleReturn.sale_id == sale.id)
                    .group_by(ReturnItem.sale_item_id)).all())
                open_items = [it for it in sale.items
                              if it.quantity - (returned.get(it.id) or ZERO) > 0]
                if not open_items:
                    continue
                out.append({"id": sale.id, "invoice_no": sale.invoice_no,
                            "created_at": sale.created_at,
                            "customer": sale.customer_name or "Walk-in",
                            "phone": sale.customer_phone or "",
                            "items": ", ".join(f"{it.product_name} × {fmt_qty(it.quantity)}"
                                               for it in sale.items),
                            "grand_total": sale.grand_total})
                if len(out) >= limit:
                    break
            return out

    def get_sale(self, actor: CurrentUser, sale_id: int | None = None,
                 invoice_no: str | None = None) -> dict:
        require_any(actor, Perm.VIEW_SALES, Perm.PROCESS_RETURN, Perm.CREATE_SALE)
        with self.db.session() as s:
            if sale_id is not None:
                sale = s.get(Sale, sale_id)
            else:
                sale = s.scalar(select(Sale).where(Sale.invoice_no == (invoice_no or "").strip()))
            if sale is None:
                raise NotFound("Sale / invoice not found.")
            returned = dict(s.execute(
                select(ReturnItem.sale_item_id, func.sum(ReturnItem.quantity))
                .join(SaleReturn).where(SaleReturn.sale_id == sale.id)
                .group_by(ReturnItem.sale_item_id)).all())
            returns = s.scalars(select(SaleReturn).where(SaleReturn.sale_id == sale.id)
                                .order_by(SaleReturn.id)).all()
            return {
                "id": sale.id, "invoice_no": sale.invoice_no, "created_at": sale.created_at,
                "status": sale.status, "tax_mode": sale.tax_mode,
                "customer_id": sale.customer_id, "customer_name": sale.customer_name or "",
                "customer_phone": sale.customer_phone or "",
                "customer_gstin": sale.customer_gstin or "",
                "customer_address": sale.customer_address or "",
                "cashier": sale.user.full_name or sale.user.username if sale.user else "",
                "gross_total": sale.gross_total, "item_discount_total": sale.item_discount_total,
                "bill_discount": sale.bill_discount, "taxable_total": sale.taxable_total,
                "cgst_total": sale.cgst_total, "sgst_total": sale.sgst_total,
                "igst_total": sale.igst_total, "tax_total": sale.tax_total,
                "round_off": sale.round_off, "grand_total": sale.grand_total,
                "notes": sale.notes or "", "void_reason": sale.void_reason or "",
                "voided_at": sale.voided_at,
                "items": [{
                    "id": it.id, "product_id": it.product_id, "product_name": it.product_name,
                    "sku": it.sku or "", "hsn_code": it.hsn_code or "", "unit": it.unit,
                    "quantity": it.quantity, "unit_price": it.unit_price,
                    "price_includes_tax": it.price_includes_tax, "gross_amount": it.gross_amount,
                    "discount_amount": it.discount_amount,
                    "bill_discount_share": it.bill_discount_share,
                    "taxable_amount": it.taxable_amount, "tax_name": it.tax_name or "",
                    "tax_rate": it.tax_rate, "cgst_amount": it.cgst_amount,
                    "sgst_amount": it.sgst_amount, "igst_amount": it.igst_amount,
                    "tax_amount": it.tax_amount, "line_total": it.line_total,
                    "returned_quantity": returned.get(it.id) or ZERO,
                } for it in sale.items],
                "payments": [{
                    "id": p.id, "method": p.method_name, "amount": p.amount,
                    "reference": p.reference or "", "description": p.description or "",
                    "created_at": p.created_at, "is_void": p.is_void,
                } for p in sale.payments],
                "returns": [{
                    "id": r.id, "return_no": r.return_no, "created_at": r.created_at,
                    "refund_total": r.refund_total, "reason": r.reason,
                } for r in returns],
            }
