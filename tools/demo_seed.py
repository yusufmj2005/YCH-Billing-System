"""DEVELOPMENT ONLY - populate a *separate* data folder with clearly labelled
demo data for manual testing and screenshots.

Refuses to run unless BUSINESSPOS_DATA_DIR points somewhere other than the
production location (%LOCALAPPDATA%\\BusinessPOS). Every name starts with
"DEMO" so demo records can never be mistaken for real business data.

    set BUSINESSPOS_DATA_DIR=%CD%\\.devdata
    python tools\\demo_seed.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_services  # noqa: E402
from app.config.constants import APP_ID, PaymentKind  # noqa: E402
from app.config.settings import AppPaths  # noqa: E402
from app.services.purchase_service import PurchaseLineRequest, PurchaseRequest  # noqa: E402
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest  # noqa: E402

DEMO_PASSWORD = "Demo-Pass-123"  # development-only demo account


def main() -> None:
    target = os.environ.get("BUSINESSPOS_DATA_DIR")
    prod = Path(os.environ.get("LOCALAPPDATA", "")) / APP_ID
    if not target or Path(target).resolve() == prod.resolve():
        sys.exit("Refusing to seed demo data: set BUSINESSPOS_DATA_DIR to a separate "
                 "development folder first.")
    paths = AppPaths(Path(target)).ensure()
    svc = build_services(paths)
    if svc.auth.has_users():
        sys.exit("This development folder already contains data.")
    admin = svc.auth.complete_setup({
        "business_name": "DEMO Business (development data)", "business_address": "DEMO address",
        "admin_username": "demo", "admin_full_name": "Demo Admin",
        "admin_password": DEMO_PASSWORD, "admin_password_confirm": DEMO_PASSWORD,
        "invoice_prefix": "DEMO-", "invoice_start_number": 1, "invoice_padding": 6,
        "invoice_title": "Invoice (DEMO)",
        "enabled_payment_methods": [k for k, *_ in
                                    __import__("app.config.constants", fromlist=["x"])
                                    .DEFAULT_PAYMENT_METHODS],
        "tax_rates": [{"name": "DEMO tax A", "rate": "5"}, {"name": "DEMO tax B", "rate": "12"}],
    })
    cats = {c["name"]: c["id"] for c in svc.catalog.list_categories()}
    taxes = [t["id"] for t in svc.catalog.list_tax_rates()]
    sup = svc.partners.save_supplier(admin, None, {"name": "DEMO Supplier"})
    cust = svc.partners.save_customer(admin, None, {"name": "DEMO Customer", "phone": "0000000000"})
    pids = []
    for i, cat in enumerate(list(cats)[:7]):
        for j in range(3):
            pids.append(svc.catalog.create_product(admin, {
                "name": f"DEMO {cat} item {j + 1}", "sku": f"DEMO-{i}{j}",
                "barcode": f"DEMO{i}{j:03d}", "category_id": cats[cat],
                "selling_price": str(50 + 25 * (i + j)), "purchase_price": str(30 + 15 * (i + j)),
                "unit": "pcs", "tax_rate_id": taxes[(i + j) % 2], "price_includes_tax": True,
                "opening_stock": "0", "min_stock_level": "5"}))
    svc.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=date.today() - timedelta(days=13),
        lines=[PurchaseLineRequest(p, Decimal(20 + (k % 4) * 5), Decimal(30 + k))
               for k, p in enumerate(pids)], supplier_invoice_no="DEMO-BILL-1"), complete=True)
    methods = {m["kind"]: m["id"] for m in svc.payment_methods.list()}
    kinds = [PaymentKind.CASH, PaymentKind.UPI, PaymentKind.DEBIT_CARD, PaymentKind.CREDIT_CARD]
    from sqlalchemy import update
    from app.models import Sale
    for n in range(24):
        lines = [SaleLineRequest(pids[(n * 3 + k) % len(pids)], Decimal(1 + k % 2))
                 for k in range(1 + n % 3)]
        with svc.db.session() as s:
            from app.services.settings_service import get_settings
            _, _, res, _ = svc.sales.build_cart(s, SaleRequest(lines=lines), get_settings(s))
        kind = kinds[n % len(kinds)]
        svc.sales.create_sale(admin, SaleRequest(
            lines=lines, customer_id=cust if n % 5 == 0 else None,
            payments=[PaymentRequest(methods[kind], res.grand_total,
                                     None if kind == PaymentKind.CASH else f"DEMO-REF-{n}")]))
    ecats = {c["name"]: c["id"] for c in svc.expenses.list_categories()}
    svc.expenses.create_expense(admin, {"category_id": ecats["Packaging"], "amount": "100",
                                        "expense_date": date.today(),
                                        "description": "DEMO expense"})
    # spread demo sales over the last 12 days (direct SQL; development only)
    from datetime import datetime
    from app.models import Payment
    with svc.db.session() as s:
        for sid in range(1, 25):
            when = datetime.now().replace(microsecond=0) - timedelta(days=(24 - sid) // 2,
                                                                     hours=sid % 5)
            s.execute(update(Sale).where(Sale.id == sid).values(created_at=when))
            s.execute(update(Payment).where(Payment.sale_id == sid).values(created_at=when))
    print(f"Demo data created in {paths.root}. Sign in as 'demo' / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
