"""Customer returns against an original invoice (atomic)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select

from app.config.constants import MovementType, PaymentDirection, Perm, SaleStatus
from app.database.database import Database
from app.models import Payment, Product, ReturnItem, Sale, SaleItem, SaleReturn
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.services.inventory_service import apply_movement
from app.services.sales_service import PaymentRequest, validate_payments
from app.services.settings_service import format_doc_no, get_settings, next_sequence
from app.utils.dates import day_end_exclusive, day_start, now
from app.utils.money import ZERO, fmt_qty, money
from app.validators import common as v


@dataclass
class ReturnLineRequest:
    sale_item_id: int
    quantity: Decimal
    restock: bool = True


@dataclass
class ReturnRequest:
    sale_id: int
    lines: list[ReturnLineRequest]
    reason: str
    refunds: list[PaymentRequest] = field(default_factory=list)
    notes: str | None = None


def _prorate(total: Decimal, already: Decimal, q: Decimal, sold: Decimal,
             returned_before: Decimal) -> Decimal:
    """Share of ``total`` for ``q`` units; the final units take the exact
    remainder so the sum of all returns equals the original line."""
    if returned_before + q == sold:
        return total - already
    return money(total * q / sold)


class ReturnService:
    def __init__(self, db: Database):
        self.db = db

    def preview(self, actor: CurrentUser, sale_id: int, lines: list[ReturnLineRequest]) -> dict:
        """Compute refund amounts without saving."""
        require(actor, Perm.PROCESS_RETURN)
        with self.db.session() as s:
            calc = self._calculate(s, sale_id, lines)
            s.rollback()
            return {"refund_total": calc["refund_total"], "taxable_total": calc["taxable_total"],
                    "tax_total": calc["tax_total"], "round_off": calc["round_off"]}

    def _calculate(self, s, sale_id: int, lines: list[ReturnLineRequest]) -> dict:
        sale = s.get(Sale, sale_id)
        if sale is None:
            raise NotFound("Original sale not found.")
        if sale.status != SaleStatus.COMPLETED:
            raise ValidationError("Returns can only be made against completed sales.")
        lines = [ln for ln in lines if ln.quantity and Decimal(ln.quantity) > 0]
        if not lines:
            raise ValidationError("Enter a return quantity for at least one item.")
        prev = {sid: (q, tx, tax, ref) for sid, q, tx, tax, ref in s.execute(
            select(ReturnItem.sale_item_id, func.sum(ReturnItem.quantity),
                   func.sum(ReturnItem.taxable_amount), func.sum(ReturnItem.tax_amount),
                   func.sum(ReturnItem.refund_amount))
            .join(SaleReturn).where(SaleReturn.sale_id == sale_id)
            .group_by(ReturnItem.sale_item_id)).all()}
        items = {it.id: it for it in sale.items}
        seen = set()
        out = []
        totals = {"taxable_total": ZERO, "tax_total": ZERO, "refund_total": ZERO,
                  "cost_total": ZERO, "round_off": ZERO}
        for ln in lines:
            item: SaleItem | None = items.get(ln.sale_item_id)
            if item is None:
                raise ValidationError("Returned item does not belong to this invoice.")
            if item.id in seen:
                raise ValidationError("Each invoice line can appear only once in a return.")
            seen.add(item.id)
            product = s.get(Product, item.product_id)
            q = v.quantity(ln.quantity, f"Return quantity of {item.product_name}",
                           allow_fraction=product.allow_fractional_qty if product else True)
            r_q, r_tx, r_tax, r_ref = prev.get(item.id, (ZERO, ZERO, ZERO, ZERO))
            r_q, r_tx, r_tax = r_q or ZERO, r_tx or ZERO, r_tax or ZERO
            available = item.quantity - r_q
            if q > available:
                raise ValidationError(
                    f"Return quantity for “{item.product_name}” ({fmt_qty(q)}) exceeds "
                    f"the quantity available to return ({fmt_qty(available)}).")
            taxable = _prorate(item.taxable_amount, r_tx, q, item.quantity, r_q)
            tax = _prorate(item.tax_amount, r_tax, q, item.quantity, r_q)
            if sale.tax_mode == "INTER":
                cgst = sgst = ZERO
                igst = tax
            else:
                cgst = money(tax / 2)
                sgst = tax - cgst
                igst = ZERO
            cost = money(item.unit_cost * q)
            out.append({"item": item, "product": product, "quantity": q, "taxable": taxable,
                        "tax": tax, "cgst": cgst, "sgst": sgst, "igst": igst,
                        "refund": taxable + tax, "cost": cost, "restock": bool(ln.restock)})
            totals["taxable_total"] += taxable
            totals["tax_total"] += tax
            totals["refund_total"] += taxable + tax
            totals["cost_total"] += cost if ln.restock else ZERO
        # The return that brings every line to fully returned also gives back
        # the invoice round-off, so total refunds equal the amount paid.
        this_return = {ln["item"].id: ln["quantity"] for ln in out}
        completes_sale = all(
            (prev.get(it.id, (ZERO,))[0] or ZERO) + this_return.get(it.id, ZERO) == it.quantity
            for it in sale.items)
        if completes_sale and sale.round_off:
            totals["round_off"] = sale.round_off
            totals["refund_total"] += sale.round_off
        return {"sale": sale, "lines": out, **totals}

    def create_return(self, actor: CurrentUser, req: ReturnRequest) -> dict:
        require(actor, Perm.PROCESS_RETURN)
        reason = v.text(req.reason, "Return reason", required=True, max_len=500)
        with self.db.session() as s:
            calc = self._calculate(s, req.sale_id, req.lines)
            sale: Sale = calc["sale"]
            refunds = validate_payments(s, req.refunds, calc["refund_total"],
                                        label="refund total")
            settings = get_settings(s)
            number = next_sequence(s, "return")
            return_no = format_doc_no(settings.get("return_prefix") or "", number, 6)
            if s.scalar(select(SaleReturn.id).where(SaleReturn.return_no == return_no)):
                raise ValidationError(f"Return number {return_no} already exists.")
            ret = SaleReturn(return_no=return_no, sale_id=sale.id, created_at=now(),
                             user_id=actor.id, reason=reason,
                             notes=v.text(req.notes, "Notes", max_len=1000),
                             taxable_total=calc["taxable_total"], tax_total=calc["tax_total"],
                             round_off=calc["round_off"], refund_total=calc["refund_total"],
                             cost_total=calc["cost_total"])
            s.add(ret)
            s.flush()
            for ln in calc["lines"]:
                item = ln["item"]
                s.add(ReturnItem(
                    return_id=ret.id, sale_item_id=item.id, product_id=item.product_id,
                    product_name=item.product_name, quantity=ln["quantity"],
                    taxable_amount=ln["taxable"], cgst_amount=ln["cgst"],
                    sgst_amount=ln["sgst"], igst_amount=ln["igst"], tax_amount=ln["tax"],
                    refund_amount=ln["refund"], restocked=ln["restock"],
                    unit_cost=item.unit_cost, cost_total=ln["cost"]))
                if ln["restock"]:
                    apply_movement(s, actor, ln["product"], ln["quantity"], MovementType.RETURN,
                                   reference_type="RETURN", reference_id=ret.id,
                                   reference_no=return_no,
                                   reason=f"Return against {sale.invoice_no}: {reason}",
                                   unit_cost=item.unit_cost)
            for method, amount, reference, description in refunds:
                s.add(Payment(direction=PaymentDirection.OUT, sale_id=sale.id, return_id=ret.id,
                              payment_method_id=method.id, method_name=method.name,
                              amount=amount, reference=reference, description=description,
                              user_id=actor.id, created_at=ret.created_at))
            s.flush()
            audit_service.record(s, actor, "RETURN_CREATED", "return", ret.id, {
                "return_no": return_no, "invoice_no": sale.invoice_no,
                "refund": str(calc["refund_total"]), "round_off": str(calc["round_off"]),
                "items": [[ln["item"].product_name, str(ln["quantity"]), ln["restock"]]
                          for ln in calc["lines"]]})
            return {"return_id": ret.id, "return_no": return_no,
                    "refund_total": calc["refund_total"]}

    def list_returns(self, actor: CurrentUser, *, date_from: date | None = None,
                     date_to: date | None = None, search: str = "", limit: int = 200,
                     offset: int = 0) -> tuple[list[dict], int]:
        require(actor, Perm.PROCESS_RETURN)
        with self.db.session() as s:
            q = select(SaleReturn).join(Sale, SaleReturn.sale_id == Sale.id)
            if date_from:
                q = q.where(SaleReturn.created_at >= day_start(date_from))
            if date_to:
                q = q.where(SaleReturn.created_at < day_end_exclusive(date_to))
            if search:
                like = f"%{search.strip()}%"
                q = q.where(or_(SaleReturn.return_no.ilike(like), Sale.invoice_no.ilike(like),
                                Sale.customer_name.ilike(like)))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(SaleReturn.id.desc()).limit(limit).offset(offset)).all()
            out = []
            for r in rows:
                pays = s.scalars(select(Payment).where(Payment.return_id == r.id)).all()
                out.append({
                    "id": r.id, "return_no": r.return_no, "created_at": r.created_at,
                    "invoice_no": r.sale.invoice_no, "sale_id": r.sale_id,
                    "customer": r.sale.customer_name or "Walk-in",
                    "items": len(r.items), "refund_total": r.refund_total,
                    "refund_methods": ", ".join(sorted({p.method_name for p in pays})),
                    "reason": r.reason, "user": r.user.username if r.user else "",
                })
            return out, total

    def get_return(self, actor: CurrentUser, return_id: int) -> dict:
        require(actor, Perm.PROCESS_RETURN)
        with self.db.session() as s:
            r = s.get(SaleReturn, return_id)
            if r is None:
                raise NotFound("Return not found.")
            pays = s.scalars(select(Payment).where(Payment.return_id == r.id)).all()
            return {
                "id": r.id, "return_no": r.return_no, "created_at": r.created_at,
                "invoice_no": r.sale.invoice_no, "customer_name": r.sale.customer_name or "",
                "customer_phone": r.sale.customer_phone or "",
                "reason": r.reason, "notes": r.notes or "",
                "taxable_total": r.taxable_total, "tax_total": r.tax_total,
                "round_off": r.round_off, "refund_total": r.refund_total,
                "user": r.user.full_name or r.user.username if r.user else "",
                "items": [{"product_name": it.product_name, "quantity": it.quantity,
                           "taxable_amount": it.taxable_amount, "tax_amount": it.tax_amount,
                           "refund_amount": it.refund_amount, "restocked": it.restocked}
                          for it in r.items],
                "refunds": [{"method": p.method_name, "amount": p.amount,
                             "reference": p.reference or "", "description": p.description or ""}
                            for p in pays],
            }
