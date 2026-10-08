"""Products, categories, tax rates and barcode generation."""
from __future__ import annotations

import shutil
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, or_, select

from app.barcode.codes import make_code
from app.config.constants import MovementType, Perm
from app.database.database import Database
from app.models import Category, InventoryMovement, Product, Supplier, TaxRate
from app.security.auth import CurrentUser, require, require_any
from app.services import audit_service
from app.services.errors import NotFound, ValidationError
from app.services.inventory_service import apply_movement, low_stock_condition
from app.services.settings_service import get_settings, next_sequence
from app.utils.money import ZERO
from app.validators import common as v


def product_dict(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "sku": p.sku or "", "barcode": p.barcode or "",
        "category_id": p.category_id, "category": p.category.name if p.category else "",
        "brand": p.brand or "", "description": p.description or "",
        "supplier_id": p.supplier_id, "supplier": p.supplier.name if p.supplier else "",
        "hsn_code": p.hsn_code or "", "purchase_price": p.purchase_price,
        "selling_price": p.selling_price, "tax_rate_id": p.tax_rate_id,
        "tax_name": p.tax_rate.name if p.tax_rate else "",
        "tax_rate": p.tax_rate.rate if p.tax_rate else ZERO,
        "price_includes_tax": p.price_includes_tax, "current_stock": p.current_stock,
        "min_stock_level": p.min_stock_level, "unit": p.unit,
        "allow_fractional_qty": p.allow_fractional_qty, "is_active": p.is_active,
        "image_path": p.image_path or "", "created_at": p.created_at, "updated_at": p.updated_at,
    }


class CatalogService:
    def __init__(self, db: Database, attachments_dir: Path | None = None):
        self.db = db
        self.attachments_dir = attachments_dir

    # ---- product images ------------------------------------------------------------
    def store_product_image(self, actor: CurrentUser, source: str | Path) -> str:
        """Copy an image into the data folder; returns the relative path to save."""
        require(actor, Perm.EDIT_PRODUCTS)
        src = Path(source)
        if src.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValidationError("Product images must be PNG or JPG files.")
        if not src.is_file() or src.stat().st_size > 5_000_000:
            raise ValidationError("The image file is missing or larger than 5 MB.")
        if self.attachments_dir is None:
            raise ValidationError("Image storage is not available.")
        folder = self.attachments_dir / "products"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{src.suffix.lower()}"
        shutil.copyfile(src, folder / name)
        return f"products/{name}"

    def image_file(self, rel: str | None) -> Path | None:
        if not rel or self.attachments_dir is None:
            return None
        p = (self.attachments_dir / rel).resolve()
        if self.attachments_dir.resolve() not in p.parents or not p.is_file():
            return None
        return p

    # ---- categories ------------------------------------------------------------
    def list_categories(self, include_inactive: bool = False) -> list[dict]:
        with self.db.session() as s:
            counts = dict(s.execute(select(Product.category_id, func.count(Product.id))
                                    .group_by(Product.category_id)).all())
            q = select(Category).order_by(Category.sort_order, Category.name)
            if not include_inactive:
                q = q.where(Category.is_active.is_(True))
            return [{"id": c.id, "name": c.name, "description": c.description or "",
                     "is_active": c.is_active, "product_count": counts.get(c.id, 0)}
                    for c in s.scalars(q)]

    def save_category(self, actor: CurrentUser, category_id: int | None, data: dict) -> int:
        require(actor, Perm.MANAGE_CATEGORIES)
        name = v.text(data.get("name"), "Category name", required=True, max_len=100)
        with self.db.session() as s:
            dup = s.scalar(select(Category.id).where(Category.name == name))
            if dup and dup != category_id:
                raise ValidationError("A category with this name already exists.")
            if category_id is None:
                max_order = s.scalar(select(func.max(Category.sort_order))) or 0
                c = Category(name=name, sort_order=max_order + 1)
                s.add(c)
                action = "CATEGORY_CREATED"
            else:
                c = s.get(Category, category_id)
                if c is None:
                    raise NotFound("Category not found.")
                action = "CATEGORY_UPDATED"
            c.name = name
            c.description = v.text(data.get("description"), "Description", max_len=500)
            if "is_active" in data:
                c.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, action, "category", c.id,
                                 {"name": name, "active": c.is_active})
            return c.id

    # ---- tax rates ---------------------------------------------------------------
    def list_tax_rates(self, include_inactive: bool = False) -> list[dict]:
        with self.db.session() as s:
            q = select(TaxRate).order_by(TaxRate.rate, TaxRate.name)
            if not include_inactive:
                q = q.where(TaxRate.is_active.is_(True))
            return [{"id": t.id, "name": t.name, "rate": t.rate,
                     "description": t.description or "", "is_active": t.is_active}
                    for t in s.scalars(q)]

    def save_tax_rate(self, actor: CurrentUser, tax_id: int | None, data: dict) -> int:
        require(actor, Perm.MANAGE_SETTINGS)
        name = v.text(data.get("name"), "Tax name", required=True, max_len=64)
        rate = v.percent(data.get("rate"), "Tax rate (%)")
        with self.db.session() as s:
            dup = s.scalar(select(TaxRate.id).where(TaxRate.name == name))
            if dup and dup != tax_id:
                raise ValidationError("A tax rate with this name already exists.")
            if tax_id is None:
                t = TaxRate(name=name, rate=rate)
                s.add(t)
                action = "TAX_RATE_CREATED"
            else:
                t = s.get(TaxRate, tax_id)
                if t is None:
                    raise NotFound("Tax rate not found.")
                action = "TAX_RATE_UPDATED"
            before = str(t.rate) if t.rate is not None else None
            t.name, t.rate = name, rate
            t.description = v.text(data.get("description"), "Description", max_len=300)
            if "is_active" in data:
                t.is_active = bool(data["is_active"])
            s.flush()
            audit_service.record(s, actor, action, "tax_rate", t.id,
                                 {"name": name, "rate": str(rate), "previous_rate": before,
                                  "active": t.is_active})
            return t.id

    # ---- products ------------------------------------------------------------------
    def list_products(self, actor: CurrentUser, *, search: str = "", category_id: int | None = None,
                      status: str = "active", low_stock_only: bool = False,
                      limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
        require_any(actor, Perm.VIEW_PRODUCTS, Perm.CREATE_SALE, Perm.CREATE_PURCHASE)
        with self.db.session() as s:
            q = select(Product)
            if status == "active":
                q = q.where(Product.is_active.is_(True))
            elif status == "inactive":
                q = q.where(Product.is_active.is_(False))
            if category_id:
                q = q.where(Product.category_id == category_id)
            if search:
                like = f"%{search.strip()}%"
                q = q.where(or_(Product.name.ilike(like), Product.sku.ilike(like),
                                Product.barcode.ilike(like), Product.brand.ilike(like)))
            if low_stock_only:
                threshold = Decimal(str(get_settings(s).get("low_stock_threshold") or "0"))
                q = q.where(low_stock_condition(threshold))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            rows = s.scalars(q.order_by(Product.name).limit(limit).offset(offset)).unique().all()
            return [product_dict(p) for p in rows], total

    def search_for_sale(self, actor: CurrentUser, term: str, limit: int = 60) -> list[dict]:
        require_any(actor, Perm.CREATE_SALE, Perm.CREATE_PURCHASE, Perm.VIEW_PRODUCTS)
        term = (term or "").strip()
        with self.db.session() as s:
            q = select(Product).where(Product.is_active.is_(True))
            if term:
                like = f"%{term}%"
                q = q.where(or_(Product.name.ilike(like), Product.sku.ilike(like),
                                Product.barcode == term, Product.brand.ilike(like)))
            rows = s.scalars(q.order_by(Product.name).limit(limit)).unique().all()
            return [product_dict(p) for p in rows]

    def find_by_code(self, actor: CurrentUser, code: str) -> dict | None:
        """Exact barcode match first, then exact SKU (active products only)."""
        require_any(actor, Perm.CREATE_SALE, Perm.CREATE_PURCHASE, Perm.VIEW_PRODUCTS)
        code = (code or "").strip()
        if not code:
            return None
        with self.db.session() as s:
            p = s.scalar(select(Product).where(Product.barcode == code,
                                               Product.is_active.is_(True)))
            if p is None:
                matches = s.scalars(select(Product).where(Product.sku == code,
                                                          Product.is_active.is_(True))).all()
                p = matches[0] if len(matches) == 1 else None
            return product_dict(p) if p else None

    def get_product(self, actor: CurrentUser, product_id: int) -> dict:
        require_any(actor, Perm.VIEW_PRODUCTS, Perm.CREATE_SALE, Perm.VIEW_INVENTORY)
        with self.db.session() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise NotFound("Product not found.")
            return product_dict(p)

    def _validate_product(self, s, data: dict, product_id: int | None) -> dict:
        settings = get_settings(s)
        clean = {
            "name": v.text(data.get("name"), "Product name", required=True, max_len=200),
            "sku": v.text(data.get("sku"), "SKU", max_len=64),
            "barcode": v.barcode_value(data.get("barcode")),
            "brand": v.text(data.get("brand"), "Brand", max_len=100),
            "description": v.text(data.get("description"), "Description", max_len=2000),
            "hsn_code": v.text(data.get("hsn_code"), "HSN/SAC code", max_len=16),
            "purchase_price": v.amount(data.get("purchase_price") or 0, "Purchase price"),
            "selling_price": v.amount(data.get("selling_price"), "Selling price"),
            "price_includes_tax": bool(data.get("price_includes_tax", True)),
            "min_stock_level": v.decimal(data.get("min_stock_level"), "Minimum stock level",
                                         required=False, min_value=0, places=3),
            "unit": v.text(data.get("unit"), "Unit", required=True, max_len=16),
            "allow_fractional_qty": bool(data.get("allow_fractional_qty", False)),
            "image_path": v.text(data.get("image_path"), "Image", max_len=255),
        }
        for fk, model, label in (("category_id", Category, "Category"),
                                 ("supplier_id", Supplier, "Supplier"),
                                 ("tax_rate_id", TaxRate, "Tax rate")):
            val = data.get(fk) or None
            if val is not None and s.get(model, val) is None:
                raise ValidationError(f"{label} not found.")
            clean[fk] = val
        if clean["sku"] and settings.get("sku_unique", True):
            dup = s.scalar(select(Product.id).where(Product.sku == clean["sku"]))
            if dup and dup != product_id:
                raise ValidationError(f"SKU “{clean['sku']}” is already used by another product.")
        if clean["barcode"]:
            dup = s.scalar(select(Product.id).where(Product.barcode == clean["barcode"]))
            if dup and dup != product_id:
                raise ValidationError(
                    f"Barcode “{clean['barcode']}” is already used by another product.")
        return clean

    def create_product(self, actor: CurrentUser, data: dict) -> int:
        require(actor, Perm.EDIT_PRODUCTS)
        with self.db.session() as s:
            return self.insert_product(s, actor, data).id

    def insert_product(self, s, actor: CurrentUser, data: dict) -> Product:
        """Validate and add one product (plus opening stock) inside session ``s``."""
        clean = self._validate_product(s, data, None)
        opening = v.decimal(data.get("opening_stock"), "Opening stock", required=False,
                            min_value=0, places=3) or ZERO
        if opening and not clean["allow_fractional_qty"] and opening != opening.to_integral_value():
            raise ValidationError("Opening stock must be a whole number for this product.")
        p = Product(**clean, current_stock=ZERO)
        s.add(p)
        s.flush()
        if opening > 0:
            if not actor.has(Perm.ADJUST_INVENTORY):
                raise ValidationError(
                    "You need the 'Adjust stock' permission to enter opening stock.")
            apply_movement(s, actor, p, opening, MovementType.ADJUSTMENT_IN,
                           reference_type="ADJUSTMENT", reason="Opening stock",
                           unit_cost=p.purchase_price)
        audit_service.record(s, actor, "PRODUCT_CREATED", "product", p.id,
                             {"name": p.name, "sku": p.sku, "opening_stock": str(opening)})
        return p

    def update_product(self, actor: CurrentUser, product_id: int, data: dict) -> None:
        require(actor, Perm.EDIT_PRODUCTS)
        with self.db.session() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise NotFound("Product not found.")
            clean = self._validate_product(s, data, product_id)
            if p.allow_fractional_qty and not clean["allow_fractional_qty"] and \
                    p.current_stock != p.current_stock.to_integral_value():
                raise ValidationError(
                    "Current stock is fractional; adjust it to a whole number first.")
            changes = {}
            for k, val in clean.items():
                old = getattr(p, k)
                if old != val:
                    changes[k] = [str(old) if old is not None else None,
                                  str(val) if val is not None else None]
                    setattr(p, k, val)
            if changes:
                audit_service.record(s, actor, "PRODUCT_UPDATED", "product", p.id,
                                     {"name": p.name, "changes": changes})

    def set_product_active(self, actor: CurrentUser, product_id: int, active: bool) -> None:
        require(actor, Perm.EDIT_PRODUCTS)
        with self.db.session() as s:
            p = s.get(Product, product_id)
            if p is None:
                raise NotFound("Product not found.")
            p.is_active = active
            audit_service.record(s, actor, "PRODUCT_ACTIVATED" if active else "PRODUCT_DEACTIVATED",
                                 "product", p.id, {"name": p.name})

    def product_history(self, actor: CurrentUser, product_id: int, limit: int = 300) -> list[dict]:
        require(actor, Perm.VIEW_INVENTORY)
        with self.db.session() as s:
            rows = s.scalars(select(InventoryMovement).where(
                InventoryMovement.product_id == product_id)
                .order_by(InventoryMovement.id.desc()).limit(limit)).all()
            return [{"created_at": m.created_at, "movement_type": m.movement_type,
                     "quantity": m.quantity, "balance_after": m.balance_after,
                     "reference_no": m.reference_no or "", "reason": m.reason or "",
                     "user": m.user.username if m.user else ""} for m in rows]

    # ---- barcodes ------------------------------------------------------------------
    def generate_barcode(self, actor: CurrentUser) -> str:
        """Return a new unused barcode value per the configured strategy.

        The value is reserved (sequence advanced) but only stored on a
        product when the user saves it."""
        require_any(actor, Perm.MANAGE_BARCODES, Perm.EDIT_PRODUCTS)
        with self.db.session() as s:
            settings = get_settings(s)
            symbology = settings.get("barcode_symbology", "CODE128")
            prefix = settings.get("barcode_prefix", "") or ""
            for _ in range(10000):
                code = make_code(symbology, prefix, next_sequence(s, "barcode"))
                if not s.scalar(select(Product.id).where(Product.barcode == code)):
                    return code
            raise ValidationError("Could not generate a unique barcode; change the prefix.")
