"""Shared fixtures. Every test gets a brand-new database in a temp folder.

Test data below is created only inside temporary test databases.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import build_services  # noqa: E402
from app.config.constants import PaymentKind  # noqa: E402
from app.config.settings import AppPaths  # noqa: E402
from app.services.sales_service import (PaymentRequest, SaleLineRequest,  # noqa: E402
                                        SaleRequest)

ADMIN_PASSWORD = "Test-Admin-123"


@pytest.fixture()
def services(tmp_path):
    paths = AppPaths(tmp_path / "data").ensure()
    svc = build_services(paths)
    yield svc
    svc.db.dispose()


@pytest.fixture()
def admin(services):
    return services.auth.complete_setup({
        "business_name": "Test Business", "admin_username": "admin",
        "admin_full_name": "Test Admin", "admin_password": ADMIN_PASSWORD,
        "admin_password_confirm": ADMIN_PASSWORD, "invoice_prefix": "T-",
        "invoice_start_number": 1, "invoice_padding": 6,
        "enabled_payment_methods": [k for k in (PaymentKind.CASH, PaymentKind.UPI,
                                                PaymentKind.DEBIT_CARD, PaymentKind.CREDIT_CARD,
                                                PaymentKind.BANK_TRANSFER, PaymentKind.OTHER)],
        "tax_rates": [{"name": "Test GST 5", "rate": "5"}, {"name": "Test GST 12", "rate": "12"}],
    })


@pytest.fixture()
def methods(services):
    return {m["kind"]: m["id"] for m in services.payment_methods.list()}


@pytest.fixture()
def taxes(services, admin):
    return {t["name"]: t["id"] for t in services.catalog.list_tax_rates()}


@pytest.fixture()
def make_product(services, admin):
    counter = {"n": 0}

    def _make(stock="10", price="100", cost="60", tax_id=None, inclusive=False, **extra):
        counter["n"] += 1
        data = {"name": f"Test Product {counter['n']}", "sku": f"TP-{counter['n']:03d}",
                "selling_price": price, "purchase_price": cost, "unit": "pcs",
                "tax_rate_id": tax_id, "price_includes_tax": inclusive, "opening_stock": stock}
        data.update(extra)
        return services.catalog.create_product(admin, data)
    return _make


@pytest.fixture()
def sell(services, admin, methods):
    def _sell(lines, payments=None, actor=None, **kw):
        req_lines = [SaleLineRequest(product_id=pid, quantity=Decimal(str(q)))
                     for pid, q in lines]
        if payments is None:
            # compute the total first so the default cash payment matches
            with services.db.session() as s:
                from app.services.settings_service import get_settings
                _, _, res, _ = services.sales.build_cart(s, SaleRequest(lines=req_lines, **kw),
                                                         get_settings(s))
            payments = [PaymentRequest(methods[PaymentKind.CASH], res.grand_total)]
        return services.sales.create_sale(actor or admin, SaleRequest(
            lines=req_lines, payments=payments, **kw))
    return _sell


def stock_of(services, admin, pid) -> Decimal:
    return services.catalog.get_product(admin, pid)["current_stock"]
