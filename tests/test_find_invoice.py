"""Lost receipt: find the original invoice by product or customer."""
from datetime import timedelta
from decimal import Decimal as D

import pytest

from app.config.constants import PaymentKind
from app.services.errors import PermissionDenied, ValidationError
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest


@pytest.fixture()
def shop(services, admin, make_product, methods):
    red = make_product(name="Merino Red", sku="MR-1", barcode="8901111111111", price="100")
    hook = make_product(name="Steel Hook 4mm", sku="HK-4", price="50")
    priya = services.partners.save_customer(admin, None, {"name": "Priya", "phone": "98400 12345"})
    return {"red": red, "hook": hook, "priya": priya}


def _sell(services, admin, methods, items, **kw):
    total = sum(price * q for _, q, price in items)
    return services.sales.create_sale(admin, SaleRequest(
        [SaleLineRequest(pid, D(q)) for pid, q, _ in items],
        [PaymentRequest(methods[PaymentKind.CASH], D(total))], **kw))


def _nos(rows):
    return [r["invoice_no"] for r in rows]


def test_find_by_product_customer_and_barcode(services, admin, shop, methods):
    s1 = _sell(services, admin, methods, [(shop["red"], 2, 100)], customer_id=shop["priya"])
    s2 = _sell(services, admin, methods, [(shop["hook"], 1, 50)])
    s3 = _sell(services, admin, methods, [(shop["red"], 1, 100), (shop["hook"], 1, 50)])
    find = services.sales.find_invoices_for_return
    assert _nos(find(admin, product="merino")) == [s3["invoice_no"], s1["invoice_no"]]
    assert _nos(find(admin, product="HK-4")) == [s3["invoice_no"], s2["invoice_no"]]
    assert _nos(find(admin, product="8901111111111")) == [s3["invoice_no"], s1["invoice_no"]]
    assert _nos(find(admin, customer="12345")) == [s1["invoice_no"]]          # phone
    assert _nos(find(admin, customer="priya", product="hook")) == []
    row = find(admin, customer="Priya")[0]
    assert row["customer"] == "Priya" and "Merino Red × 2" in row["items"]


def test_excludes_fully_returned_and_voided(services, admin, shop, methods):
    full = _sell(services, admin, methods, [(shop["red"], 1, 100)])
    part = _sell(services, admin, methods, [(shop["red"], 2, 100)])
    void = _sell(services, admin, methods, [(shop["red"], 1, 100)])
    services.sales.void_sale(admin, void["sale_id"], "mistake")
    for sale, qty in ((full, 1), (part, 1)):
        item = services.sales.get_sale(admin, sale["sale_id"])["items"][0]
        services.returns.create_return(admin, ReturnRequest(
            sale["sale_id"], [ReturnLineRequest(item["id"], D(qty))], "test",
            [PaymentRequest(methods[PaymentKind.CASH], D(100))]))
    assert _nos(services.sales.find_invoices_for_return(admin, product="merino")) == [
        part["invoice_no"]]


def test_period_and_input_rules(services, admin, shop, methods, monkeypatch):
    _sell(services, admin, methods, [(shop["red"], 1, 100)])
    import app.services.sales_service as ss
    real_date = ss.date

    class Later(real_date):
        @classmethod
        def today(cls):
            return real_date.today() + timedelta(days=40)
    monkeypatch.setattr(ss, "date", Later)
    assert services.sales.find_invoices_for_return(admin, product="merino", days=30) == []
    assert len(services.sales.find_invoices_for_return(admin, product="merino", days=90)) == 1
    with pytest.raises(ValidationError):
        services.sales.find_invoices_for_return(admin, product="  ", customer="")


def test_needs_return_permission(services, admin, shop):
    role = services.users.save_role(admin, None, "Viewer", "", ["VIEW_SALES"])
    services.users.create_user(admin, {"username": "viewer", "password": "Viewer-123",
                                       "role_id": role, "must_change_password": False})
    with pytest.raises(PermissionDenied):
        services.sales.find_invoices_for_return(services.auth.login("viewer", "Viewer-123"),
                                                product="merino")


def test_dialog_loads_chosen_invoice(services, admin, shop, methods, monkeypatch):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from app.ui.context import AppContext
    from app.ui.dialogs import return_dialog as rd
    QApplication.instance() or QApplication([])
    sale = _sell(services, admin, methods, [(shop["red"], 2, 100)], customer_id=shop["priya"])
    ctx = AppContext(services=services, user=admin)

    finder = rd.FindInvoiceDialog(None, ctx)
    finder.customer.setText("98400")
    finder.search()
    assert finder.table.model.rows[0]["invoice_no"] == sale["invoice_no"]
    finder.close()

    def fake_exec(self):
        self.customer.setText("Priya")
        self.search()
        self._choose(self.table.model.rows[0])
        return 1
    monkeypatch.setattr(rd.FindInvoiceDialog, "exec", fake_exec)
    dlg = rd.ReturnDialog(None, ctx)
    dlg.find_invoice()
    assert dlg.sale is not None and dlg.sale["invoice_no"] == sale["invoice_no"]
    dlg.close()
