"""Inventory ledger. ``apply_movement`` is the ONLY code path that changes
``products.current_stock``; it always writes an ``inventory_movements`` row
inside the caller's transaction."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config.constants import MovementType, Perm
from app.database.database import Database
from app.models import Category, InventoryMovement, Product
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import InsufficientStock, NotFound, ValidationError
from app.services.settings_service import get_settings
from app.utils.dates import day_end_exclusive, day_start
from app.utils.money import ZERO, fmt_qty, money
from app.validators import common as v


def apply_movement(s: Session, actor: CurrentUser, product: Product, delta: Decimal,
                   movement_type: str, *, reference_type: str | None = None,
                   reference_id: int | None = None, reference_no: str | None = None,
                   reason: str | None = None, unit_cost: Decimal | None = None,
                   allow_negative: bool = False) -> InventoryMovement:
    if delta == 0:
        raise ValidationError("Stock movement quantity cannot be zero.")
    new_balance = (product.current_stock or ZERO) + delta
    if new_balance < 0 and not allow_negative:
        raise InsufficientStock(
            f"Insufficient stock for “{product.name}”. "
            f"Available: {fmt_qty(product.current_stock)} {product.unit}.")
    product.current_stock = new_balance
    m = InventoryMovement(
        product_id=product.id, movement_type=movement_type, quantity=delta,
        balance_after=new_balance, unit_cost=unit_cost, user_id=actor.id,
        reference_type=reference_type, reference_id=reference_id, reference_no=reference_no,
        reason=reason,
    )
    s.add(m)
    s.flush()
    return m


def low_stock_condition(threshold: Decimal):
    return Product.current_stock <= func.coalesce(Product.min_stock_level, threshold)


class InventoryService:
    def __init__(self, db: Database):
        self.db = db

    def adjust_stock(self, actor: CurrentUser, product_id: int, *, direction: str,
                     quantity, reason: str) -> dict:
        """direction: 'IN', 'OUT' or 'SET' (physical count)."""
        require(actor, Perm.ADJUST_INVENTORY)
        reason = v.text(reason, "Reason", required=True, max_len=500)
        with self.db.session() as s:
            product = s.get(Product, product_id)
            if product is None:
                raise NotFound("Product not found.")
            if direction == "SET":
                target = v.decimal(quantity, "Counted quantity", min_value=0, places=3)
                delta = target - product.current_stock
                if delta == 0:
                    raise ValidationError("Counted quantity equals current stock; nothing to adjust.")
            else:
                q = v.quantity(quantity, allow_fraction=product.allow_fractional_qty)
                delta = q if direction == "IN" else -q
            if not product.allow_fractional_qty and delta != delta.to_integral_value():
                raise ValidationError("This product only allows whole quantities.")
            settings = get_settings(s)
            mtype = MovementType.ADJUSTMENT_IN if delta > 0 else MovementType.ADJUSTMENT_OUT
            m = apply_movement(s, actor, product, delta, mtype, reference_type="ADJUSTMENT",
                               reason=reason, unit_cost=product.purchase_price,
                               allow_negative=bool(settings.get("allow_negative_stock")))
            audit_service.record(s, actor, "STOCK_ADJUSTED", "product", product.id, {
                "product": product.name, "change": str(delta),
                "balance": str(product.current_stock), "reason": reason})
            return {"movement_id": m.id, "balance": product.current_stock}

    def movements(self, actor: CurrentUser, *, product_id: int | None = None,
                  movement_type: str | None = None, date_from: date | None = None,
                  date_to: date | None = None, search: str = "", limit: int = 200,
                  offset: int = 0) -> tuple[list[dict], int]:
        require(actor, Perm.VIEW_INVENTORY)
        with self.db.session() as s:
            q = select(InventoryMovement).join(Product)
            if product_id:
                q = q.where(InventoryMovement.product_id == product_id)
            if movement_type:
                q = q.where(InventoryMovement.movement_type == movement_type)
            if date_from:
                q = q.where(InventoryMovement.created_at >= day_start(date_from))
            if date_to:
                q = q.where(InventoryMovement.created_at < day_end_exclusive(date_to))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Product.name.ilike(like), Product.sku.ilike(like),
                                InventoryMovement.reference_no.ilike(like)))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(InventoryMovement.id.desc()).limit(limit)
                             .offset(offset)).all()
            return [{
                "id": m.id, "created_at": m.created_at, "product_id": m.product_id,
                "product": m.product.name, "sku": m.product.sku or "",
                "movement_type": m.movement_type, "quantity": m.quantity,
                "balance_after": m.balance_after, "unit": m.product.unit,
                "reference_no": m.reference_no or "", "reason": m.reason or "",
                "user": m.user.username if m.user else "",
            } for m in rows], total

    def stock_levels(self, actor: CurrentUser, *, search: str = "", category_id: int | None = None,
                     low_only: bool = False, include_inactive: bool = False) -> list[dict]:
        require(actor, Perm.VIEW_INVENTORY)
        with self.db.session() as s:
            threshold = Decimal(str(get_settings(s).get("low_stock_threshold") or "0"))
            q = select(Product).outerjoin(Category, Product.category_id == Category.id)
            if not include_inactive:
                q = q.where(Product.is_active.is_(True))
            if search:
                like = f"%{search}%"
                q = q.where(or_(Product.name.ilike(like), Product.sku.ilike(like),
                                Product.barcode == search))
            if category_id:
                q = q.where(Product.category_id == category_id)
            if low_only:
                q = q.where(low_stock_condition(threshold))
            out = []
            for p in s.scalars(q.order_by(Product.name)):
                level = p.min_stock_level if p.min_stock_level is not None else threshold
                out.append({
                    "id": p.id, "name": p.name, "sku": p.sku or "", "barcode": p.barcode or "",
                    "category": p.category.name if p.category else "",
                    "unit": p.unit, "current_stock": p.current_stock, "min_stock": level,
                    "purchase_price": p.purchase_price, "selling_price": p.selling_price,
                    "stock_value": money(p.current_stock * p.purchase_price),
                    "is_low": p.current_stock <= level, "is_active": p.is_active,
                })
            return out

    def summary(self, actor: CurrentUser | None = None) -> dict:
        """Valuation at current cost price (purchase price)."""
        with self.db.session() as s:
            threshold = Decimal(str(get_settings(s).get("low_stock_threshold") or "0"))
            value = ZERO
            count = 0
            for stock, cost in s.execute(select(Product.current_stock, Product.purchase_price)
                                         .where(Product.is_active.is_(True))):
                count += 1
                if stock > 0:
                    value += stock * cost
            low = s.scalar(select(func.count(Product.id)).where(
                Product.is_active.is_(True), low_stock_condition(threshold)))
            return {"active_products": count, "inventory_value": money(value), "low_stock": low}

    def verify_ledger(self) -> list[dict]:
        """Products whose stock differs from the sum of their movements."""
        with self.db.session() as s:
            sums = dict(s.execute(select(InventoryMovement.product_id,
                                         func.sum(InventoryMovement.quantity))
                                  .group_by(InventoryMovement.product_id)).all())
            bad = []
            for p in s.scalars(select(Product)):
                expected = sums.get(p.id) or ZERO
                if expected != p.current_stock:
                    bad.append({"product_id": p.id, "stock": p.current_stock,
                                "ledger": expected})
            return bad
