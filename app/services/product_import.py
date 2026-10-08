"""Bulk product import from a CSV file (e.g. saved from Excel).

All-or-nothing: every row is validated with the same rules as the product
form; if any row has a problem nothing is saved and every problem is reported
with its row number. ``dry_run`` checks the file without saving anything.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select

from app.config.constants import Perm
from app.database.database import Database
from app.models import Category, TaxRate
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.catalog_service import CatalogService
from app.services.errors import BusinessError, ValidationError
from app.services.settings_service import get_settings

MAX_ROWS = 20000

# (column, required, help shown in the template)
COLUMNS: list[tuple[str, bool, str]] = [
    ("name", True, "Product name"),
    ("sku", False, "Your item code (unique)"),
    ("barcode", False, "Barcode printed on the item (unique)"),
    ("category", False, "Created automatically if it does not exist"),
    ("brand", False, ""),
    ("hsn_code", False, "HSN/SAC code"),
    ("unit", True, "e.g. pcs, ball, skein, m"),
    ("purchase_price", False, "Cost price per unit"),
    ("selling_price", True, "Selling price per unit"),
    ("tax_rate", False, "Exact name of a tax rate set up in Settings, e.g. GST 5%"),
    ("price_includes_tax", False, "yes / no (blank = your default setting)"),
    ("min_stock_level", False, "Low-stock alert level"),
    ("allow_fractional_qty", False, "yes / no - e.g. yes for yarn sold by the metre"),
    ("opening_stock", False, "Quantity in stock today"),
    ("description", False, ""),
]
COLUMN_NAMES = [c for c, _, _ in COLUMNS]
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}


@dataclass
class ImportResult:
    rows: int = 0
    created: int = 0
    new_categories: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)   # "Row 5: message"
    dry_run: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def write_template(path: str | Path) -> Path:
    """A ready-to-fill CSV (opens in Excel) with the expected header row."""
    path = Path(path)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerow(COLUMN_NAMES)
    return path


def read_csv(path: str | Path) -> list[dict]:
    """Read the file into ``{column: text}`` rows (header names are case-insensitive)."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):        # Excel saves "CSV UTF-8" or ANSI
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost anything
        raise ValidationError("The file could not be read. Save it from Excel as CSV UTF-8.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader]
    if not rows:
        raise ValidationError("The file is empty.")
    header = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    unknown = [h for h in header if h and h not in COLUMN_NAMES]
    if unknown:
        raise ValidationError(
            f"Unknown column(s): {', '.join(unknown)}. Use the template's column names.")
    missing = [c for c, req, _ in COLUMNS if req and c not in header]
    if missing:
        raise ValidationError(f"Missing required column(s): {', '.join(missing)}.")
    out = []
    for values in rows[1:]:
        if not any(v.strip() for v in values):
            continue                                   # skip blank lines
        out.append({h: (values[i].strip() if i < len(values) else "")
                    for i, h in enumerate(header) if h})
    if len(out) > MAX_ROWS:
        raise ValidationError(f"Import at most {MAX_ROWS} products per file.")
    return out


def _flag(value: str, label: str, default: bool) -> bool:
    s = (value or "").strip().lower()
    if not s:
        return default
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValidationError(f"{label} must be yes or no.")


class ProductImportService:
    def __init__(self, db: Database, catalog: CatalogService):
        self.db = db
        self.catalog = catalog

    def import_rows(self, actor: CurrentUser, rows: list[dict], *,
                    dry_run: bool = True) -> ImportResult:
        require(actor, Perm.EDIT_PRODUCTS)
        res = ImportResult(rows=len(rows), dry_run=dry_run)
        if not rows:
            res.errors.append("The file has no product rows.")
            return res
        needs_stock = any((r.get("opening_stock") or "").strip() not in ("", "0")
                          for r in rows)
        if needs_stock and not actor.has(Perm.ADJUST_INVENTORY):
            res.errors.append("You need the 'Adjust stock' permission to import opening stock.")
            return res
        with self.db.session() as s:
            default_incl = bool(get_settings(s).get("default_price_includes_tax", True))
            taxes = {t.name.strip().lower(): t for t in s.scalars(select(TaxRate))}
            for n, row in enumerate(rows, start=2):          # row 1 is the header
                try:
                    with s.begin_nested():
                        self._import_one(s, actor, row, taxes, default_incl, res)
                except BusinessError as exc:
                    res.errors.append(f"Row {n}: {exc}")
            if res.errors or dry_run:
                s.rollback()
                if res.errors:
                    res.created = 0
                return res
            audit_service.record(s, actor, "PRODUCTS_IMPORTED", "product", None,
                                 {"count": res.created, "new_categories": res.new_categories})
        return res

    def _import_one(self, s, actor: CurrentUser, row: dict, taxes: dict, default_incl: bool,
                    res: ImportResult) -> None:
        data = {k: row.get(k, "") for k in ("name", "sku", "barcode", "brand", "hsn_code",
                                             "unit", "purchase_price", "selling_price",
                                             "min_stock_level", "opening_stock",
                                             "description")}
        if not (data["selling_price"] or "").strip():
            raise ValidationError("Selling price is required.")
        data["price_includes_tax"] = _flag(row.get("price_includes_tax", ""),
                                           "price_includes_tax", default_incl)
        data["allow_fractional_qty"] = _flag(row.get("allow_fractional_qty", ""),
                                             "allow_fractional_qty", False)
        tax_name = (row.get("tax_rate") or "").strip()
        if tax_name:
            tax = taxes.get(tax_name.lower())
            if tax is None or not tax.is_active:
                raise ValidationError(f"Tax rate “{tax_name}” is not set up (see Settings › Tax).")
            data["tax_rate_id"] = tax.id
        cat_name = (row.get("category") or "").strip()
        new_category = None
        if cat_name:
            cat = s.scalar(select(Category).where(Category.name == cat_name))
            if cat is None:
                if not actor.has(Perm.MANAGE_CATEGORIES):
                    raise ValidationError(
                        f"Category “{cat_name}” does not exist and you may not create "
                        "categories.")
                if len(cat_name) > 100:
                    raise ValidationError("Category must be at most 100 characters.")
                order = (s.scalar(select(func.max(Category.sort_order))) or 0) + 1
                cat = Category(name=cat_name, sort_order=order)
                s.add(cat)
                s.flush()
                new_category = cat_name
            data["category_id"] = cat.id
        self.catalog.insert_product(s, actor, data)
        res.created += 1
        if new_category:
            res.new_categories.append(new_category)
