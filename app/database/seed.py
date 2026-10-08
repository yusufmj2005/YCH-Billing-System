"""System seed data.

Only the application's own configuration vocabulary is seeded: permissions,
default roles, the payment methods / product categories / expense categories
listed in the specification, document sequences and default settings.

No business information (names, prices, stock, customers, suppliers,
employees, tax rates, financial figures) is ever seeded here.
Demo data for development lives in ``tools/demo_seed.py`` and refuses to run
against the production data folder.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.constants import (ADMIN_ROLE_NAME, DEFAULT_EXPENSE_CATEGORIES,
                                  DEFAULT_PAYMENT_METHODS, DEFAULT_PRODUCT_CATEGORIES,
                                  DEFAULT_ROLES, DEFAULT_UNITS, PERMISSION_CATALOG, TaxMode)
from app.models import (Category, ExpenseCategory, PaymentMethod, Permission, Role,
                        Sequence, Setting)

# Structural defaults only. Business details start blank and are captured by
# the first-run setup wizard.
DEFAULT_SETTINGS: dict[str, object] = {
    "setup_completed": False,
    # Business
    "business_name": "",
    "business_address": "",
    "business_phone": "",
    "business_email": "",
    "business_gstin": "",
    "business_state": "",
    "logo_path": "",
    "currency_symbol": "₹",
    # Billing
    "invoice_prefix": "",
    "invoice_padding": 6,
    "invoice_paper": "A4",          # A4 | RECEIPT_80MM
    "invoice_title": "Tax Invoice",
    "invoice_footer": "",
    "auto_print_invoice": False,
    "round_off_total": False,
    "default_tax_mode": TaxMode.INTRA,
    "return_prefix": "RET-",
    "purchase_prefix": "PUR-",
    # Tax
    "default_price_includes_tax": True,
    # Inventory
    "low_stock_threshold": "0",
    "allow_negative_stock": False,
    "sku_unique": True,
    "units": DEFAULT_UNITS,
    "barcode_symbology": "CODE128",  # CODE128 | EAN13
    "barcode_prefix": "",
    # Discounts / security
    "max_discount_percent": "",     # blank = no limit
    "idle_logout_minutes": 0,
    # Backup
    "auto_backup_on_start": True,
    "backup_keep_count": 30,
    "backup_on_exit": True,
    "backup_copy_folder": "",       # second copy of automatic backups (USB / cloud folder)
    # UPI QR at checkout (blank = off)
    "upi_id": "",
    "upi_payee_name": "",
}


def sync_permissions(session: Session) -> None:
    """Insert permissions added by newer versions; admin role gets all."""
    existing = {p.code: p for p in session.scalars(select(Permission))}
    for code, name, group in PERMISSION_CATALOG:
        p = existing.get(code)
        if p is None:
            session.add(Permission(code=code, name=name, group_name=group))
        else:
            p.name, p.group_name = name, group
    session.flush()
    admin = session.scalar(select(Role).where(Role.is_system.is_(True)))
    if admin is not None:
        admin.permissions = list(session.scalars(select(Permission)))


def seed_initial_data(session: Session) -> None:
    sync_permissions(session)
    perms = {p.code: p for p in session.scalars(select(Permission))}
    for name, (desc, codes) in DEFAULT_ROLES.items():
        session.add(Role(name=name, description=desc, is_system=(name == ADMIN_ROLE_NAME),
                         permissions=[perms[c] for c in sorted(codes)]))
    for i, (kind, name, allows_ref, req_desc) in enumerate(DEFAULT_PAYMENT_METHODS):
        session.add(PaymentMethod(kind=kind, name=name, allows_reference=allows_ref,
                                  requires_description=req_desc, is_system=True,
                                  sort_order=i))
    for i, name in enumerate(DEFAULT_PRODUCT_CATEGORIES):
        session.add(Category(name=name, sort_order=i))
    for name in DEFAULT_EXPENSE_CATEGORIES:
        session.add(ExpenseCategory(name=name))
    for seq in ("invoice", "purchase", "return", "barcode"):
        session.add(Sequence(name=seq, next_value=1))
    ensure_default_settings(session)


def ensure_default_settings(session: Session) -> None:
    existing = set(session.scalars(select(Setting.key)))
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            session.add(Setting(key=key, value=json.dumps(value)))
