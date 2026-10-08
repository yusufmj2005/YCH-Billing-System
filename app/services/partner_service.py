"""Suppliers and customers."""
from __future__ import annotations

from sqlalchemy import func, or_, select

from app.config.constants import Perm, PurchaseStatus, SaleStatus
from app.database.database import Database
from app.models import Customer, Purchase, PurchaseItem, Sale, SaleReturn, Supplier
from app.security.auth import CurrentUser, require, require_any
from app.services import audit_service
from app.services.errors import NotFound
from app.utils.money import ZERO
from app.validators import common as v


def _contact_fields(data: dict) -> dict:
    return {
        "name": v.text(data.get("name"), "Name", required=True, max_len=150),
        "phone": v.phone(data.get("phone")),
        "email": v.email(data.get("email")),
        "address": v.text(data.get("address"), "Address", max_len=1000),
        "gstin": v.gstin(data.get("gstin")),
        "notes": v.text(data.get("notes"), "Notes", max_len=2000),
    }


def _row(o) -> dict:
    d = {"id": o.id, "name": o.name, "phone": o.phone or "", "email": o.email or "",
         "address": o.address or "", "gstin": o.gstin or "", "notes": o.notes or "",
         "is_active": o.is_active, "created_at": o.created_at}
    if isinstance(o, Supplier):
        d["contact_person"] = o.contact_person or ""
    return d


class PartnerService:
    def __init__(self, db: Database):
        self.db = db

    # ---- suppliers ---------------------------------------------------------------
    def list_suppliers(self, actor: CurrentUser, search: str = "",
                       include_inactive: bool = False) -> list[dict]:
        require_any(actor, Perm.VIEW_SUPPLIERS, Perm.CREATE_PURCHASE, Perm.EDIT_PRODUCTS)
        with self.db.session() as s:
            q = select(Supplier)
            if not include_inactive:
                q = q.where(Supplier.is_active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Supplier.name.ilike(like), Supplier.phone.ilike(like),
                                Supplier.contact_person.ilike(like), Supplier.gstin.ilike(like)))
            return [_row(x) for x in s.scalars(q.order_by(Supplier.name))]

    def save_supplier(self, actor: CurrentUser, supplier_id: int | None, data: dict) -> int:
        require(actor, Perm.EDIT_SUPPLIERS)
        fields = _contact_fields(data)
        fields["contact_person"] = v.text(data.get("contact_person"), "Contact person", max_len=150)
        with self.db.session() as s:
            if supplier_id is None:
                obj = Supplier(**fields)
                s.add(obj)
                action = "SUPPLIER_CREATED"
            else:
                obj = s.get(Supplier, supplier_id)
                if obj is None:
                    raise NotFound("Supplier not found.")
                for k, val in fields.items():
                    setattr(obj, k, val)
                action = "SUPPLIER_UPDATED"
            if "is_active" in data:
                obj.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, action, "supplier", obj.id,
                                 {"name": obj.name, "active": obj.is_active})
            return obj.id

    def supplier_history(self, actor: CurrentUser, supplier_id: int) -> dict:
        require(actor, Perm.VIEW_SUPPLIERS)
        with self.db.session() as s:
            sup = s.get(Supplier, supplier_id)
            if sup is None:
                raise NotFound("Supplier not found.")
            purchases = s.scalars(select(Purchase).where(Purchase.supplier_id == supplier_id)
                                  .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())).all()
            products = s.execute(
                select(PurchaseItem.product_id, PurchaseItem.product_name,
                       func.sum(PurchaseItem.quantity), func.sum(PurchaseItem.line_total),
                       func.max(Purchase.purchase_date))
                .join(Purchase).where(Purchase.supplier_id == supplier_id,
                                      Purchase.status == PurchaseStatus.COMPLETED)
                .group_by(PurchaseItem.product_id, PurchaseItem.product_name)
                .order_by(PurchaseItem.product_name)).all()
            return {
                "supplier": _row(sup),
                "purchases": [{
                    "id": p.id, "purchase_no": p.purchase_no, "purchase_date": p.purchase_date,
                    "supplier_invoice_no": p.supplier_invoice_no or "", "status": p.status,
                    "grand_total": p.grand_total, "amount_paid": p.amount_paid,
                    "payment_status": p.payment_status} for p in purchases],
                "products": [{"product_id": pid, "product": name, "quantity": q or ZERO,
                              "total": t or ZERO, "last_purchase": last}
                             for pid, name, q, t, last in products],
            }

    # ---- customers ---------------------------------------------------------------
    def list_customers(self, actor: CurrentUser, search: str = "",
                       include_inactive: bool = False, limit: int = 500) -> list[dict]:
        require_any(actor, Perm.VIEW_CUSTOMERS, Perm.CREATE_SALE)
        with self.db.session() as s:
            q = select(Customer)
            if not include_inactive:
                q = q.where(Customer.is_active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Customer.name.ilike(like), Customer.phone.ilike(like),
                                Customer.email.ilike(like)))
            return [_row(x) for x in s.scalars(q.order_by(Customer.name).limit(limit))]

    def save_customer(self, actor: CurrentUser, customer_id: int | None, data: dict) -> int:
        require(actor, Perm.EDIT_CUSTOMERS)
        fields = _contact_fields(data)
        with self.db.session() as s:
            if customer_id is None:
                obj = Customer(**fields)
                s.add(obj)
                action = "CUSTOMER_CREATED"
            else:
                obj = s.get(Customer, customer_id)
                if obj is None:
                    raise NotFound("Customer not found.")
                for k, val in fields.items():
                    setattr(obj, k, val)
                action = "CUSTOMER_UPDATED"
            if "is_active" in data:
                obj.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, action, "customer", obj.id, {"name": obj.name})
            return obj.id

    def get_customer(self, actor: CurrentUser, customer_id: int) -> dict:
        require_any(actor, Perm.VIEW_CUSTOMERS, Perm.CREATE_SALE)
        with self.db.session() as s:
            c = s.get(Customer, customer_id)
            if c is None:
                raise NotFound("Customer not found.")
            return _row(c)

    def customer_history(self, actor: CurrentUser, customer_id: int) -> dict:
        require(actor, Perm.VIEW_CUSTOMERS)
        with self.db.session() as s:
            c = s.get(Customer, customer_id)
            if c is None:
                raise NotFound("Customer not found.")
            sales = s.scalars(select(Sale).where(Sale.customer_id == customer_id)
                              .order_by(Sale.id.desc())).all()
            refunds = dict(s.execute(
                select(SaleReturn.sale_id, func.sum(SaleReturn.refund_total))
                .join(Sale).where(Sale.customer_id == customer_id)
                .group_by(SaleReturn.sale_id)).all())
            completed = [x for x in sales if x.status == SaleStatus.COMPLETED]
            return {
                "customer": _row(c),
                "sales": [{"id": x.id, "invoice_no": x.invoice_no, "created_at": x.created_at,
                           "status": x.status, "grand_total": x.grand_total,
                           "refunded": refunds.get(x.id) or ZERO,
                           "items": len(x.items)} for x in sales],
                "total_spent": sum((x.grand_total for x in completed), ZERO)
                - sum((refunds.get(x.id) or ZERO for x in completed), ZERO),
                "invoice_count": len(completed),
            }
