"""Offscreen UI smoke tests: every page builds and loads without errors."""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.ui.context import AppContext  # noqa: E402
from app.ui.styles.theme import apply_theme  # noqa: E402
from app.ui.windows.main_window import NAVIGATION, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture()
def no_dialogs(monkeypatch):
    shown = []
    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _n=name, **k: shown.append((_n, a)))
    return shown


def test_all_pages_load(qapp, services, admin, make_product, sell, no_dialogs):
    pid = make_product(stock="5")
    sell([(pid, 1)])
    win = MainWindow(AppContext(services=services, user=admin))
    for _, items in NAVIGATION:
        for key, *_ in items:
            win.navigate(key)
            qapp.processEvents()
            assert key in win.pages, key
    assert no_dialogs == [], no_dialogs
    win.close()


def test_pos_cart_flow(qapp, services, admin, make_product, taxes, no_dialogs):
    make_product(stock="5", price="100", barcode="SCAN-1", tax_id=taxes["Test GST 12"])
    win = MainWindow(AppContext(services=services, user=admin))
    win.navigate("pos")
    pos = win.pages["pos"]
    # simulate a barcode scanner: type the code + Enter
    pos.search.setText("SCAN-1")
    pos._search_enter()
    assert len(pos.cart) == 1
    pos.change_qty(+1)
    assert pos.cart[0]["qty"] == Decimal(2)
    assert pos.result.grand_total == Decimal("224.00")
    pos.cart[0]["disc_amount"] = Decimal("10")
    pos.refresh_cart(0)
    assert pos.result.grand_total == Decimal("212.80")
    # stock limit enforced in the cart
    for _ in range(5):
        pos.change_qty(+1)
    assert pos.cart[0]["qty"] == Decimal(5)
    pos.remove_line()
    assert pos.cart == []
    assert no_dialogs == []
    win.close()


def test_checkout_dialog_split_payment(qapp, services, admin, make_product, methods,
                                       no_dialogs, monkeypatch):
    """Drive the real checkout dialog: Cash 100 + UPI rest with a reference."""
    from app.ui.dialogs import checkout_dialog as cd
    monkeypatch.setattr(cd.SaleCompleteDialog, "exec", lambda self: 0)
    pid = make_product(stock="5", price="250")
    win = MainWindow(AppContext(services=services, user=admin))
    win.navigate("pos")
    pos = win.pages["pos"]
    pos.add_product(services.catalog.get_product(admin, pid))
    from app.services.sales_service import SaleLineRequest, SaleRequest
    req = SaleRequest(lines=[SaleLineRequest(pid, Decimal(1))])
    dlg = cd.CheckoutDialog(win, win.ctx, pos.compute(), req)
    dlg.amount.setText("100")
    assert dlg._add_payment()
    upi = next(i for i, m in enumerate(dlg.methods) if m["kind"] == "UPI")
    dlg.method_group.button(upi).click()
    assert dlg.amount.text() == "150.00"
    dlg.reference.setText("UPI-TEST-REF")
    dlg._complete()
    assert dlg.sale is not None, no_dialogs
    sale = services.sales.get_sale(admin, dlg.sale["sale_id"])
    assert [(p["method"], p["amount"], p["reference"]) for p in sale["payments"]] == [
        ("Cash", Decimal("100.00"), ""), ("UPI", Decimal("150.00"), "UPI-TEST-REF")]
    assert services.catalog.get_product(admin, pid)["current_stock"] == Decimal(4)
    win.close()


def test_dialogs_open(qapp, services, admin, make_product, sell, tmp_path, no_dialogs):
    from PIL import Image
    from app.ui.dialogs.product_dialog import ProductDialog
    from app.ui.dialogs.purchase_dialog import PurchaseDialog
    from app.ui.dialogs.return_dialog import ReturnDialog
    from app.ui.dialogs.sale_detail_dialog import SaleDetailDialog
    ctx = AppContext(services=services, user=admin)
    pid = make_product(stock="5")
    img = tmp_path / "p.png"
    Image.new("RGB", (40, 40), "white").save(img)
    rel = services.catalog.store_product_image(admin, img)
    data = services.catalog.get_product(admin, pid)
    data["image_path"] = rel
    services.catalog.update_product(admin, pid, data)
    assert services.catalog.image_file(rel) is not None
    assert services.catalog.image_file("../../outside.png") is None
    ProductDialog(None, ctx, services.catalog.get_product(admin, pid)).close()
    ProductDialog(None, ctx).close()
    PurchaseDialog(None, ctx).close()
    res = sell([(pid, 2)])
    SaleDetailDialog(None, ctx, res["sale_id"]).close()
    rd = ReturnDialog(None, ctx, res["invoice_no"])
    rd.qty_edits[0].setText("1")
    assert rd.refund_total > 0
    rd.close()
    assert no_dialogs == []


def test_cashier_navigation_is_restricted(qapp, services, admin):
    roles = {r["name"]: r["id"] for r in services.users.list_roles(admin)}
    services.users.create_user(admin, {"username": "cash2", "password": "Cashier-Pass-9",
                                       "role_id": roles["Cashier"],
                                       "must_change_password": False})
    cashier = services.auth.login("cash2", "Cashier-Pass-9")
    win = MainWindow(AppContext(services=services, user=cashier))
    assert "pos" in win.nav_buttons
    for hidden in ("settings", "users", "backup", "audit", "reports", "expenses", "payroll"):
        assert hidden not in win.nav_buttons
    assert win.stack.currentWidget() is win.pages["pos"]  # first allowed page
    win.close()
