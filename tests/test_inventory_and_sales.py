from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select, text

from app.config.constants import PaymentKind
from app.models import InventoryMovement, Payment, Sale, SaleItem
from app.services.errors import InsufficientStock, ValidationError
from app.services.purchase_service import PurchaseLineRequest, PurchaseRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest
from tests.conftest import stock_of


# ---------------------------------------------------------------- inventory ----
def test_purchase_increases_stock(services, admin, make_product):
    pid = make_product(stock="0", cost="50")
    sup = services.partners.save_supplier(admin, None, {"name": "Test Supplier"})
    res = services.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=date.today(),
        lines=[PurchaseLineRequest(pid, D("12"), D("55.00"), D("0"), D("5"))]), complete=True)
    assert stock_of(services, admin, pid) == D("12")
    p = services.purchases.get_purchase(admin, res["purchase_id"])
    assert p["status"] == "COMPLETED"
    assert p["grand_total"] == D("693.00")  # 660 + 5% tax
    # cost price updated to net unit cost
    assert services.catalog.get_product(admin, pid)["purchase_price"] == D("55.00")
    rows, _ = services.inventory.movements(admin, product_id=pid, movement_type="PURCHASE")
    assert rows[0]["quantity"] == D("12") and rows[0]["reference_no"] == p["purchase_no"]


def test_draft_purchase_does_not_change_stock(services, admin, make_product):
    pid = make_product(stock="3")
    sup = services.partners.save_supplier(admin, None, {"name": "Test Supplier"})
    res = services.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=date.today(),
        lines=[PurchaseLineRequest(pid, D("5"), D("10"))]))
    assert stock_of(services, admin, pid) == D("3")
    services.purchases.complete(admin, res["purchase_id"])
    assert stock_of(services, admin, pid) == D("8")
    services.purchases.cancel(admin, res["purchase_id"], "entered twice")
    assert stock_of(services, admin, pid) == D("3")


def test_purchase_payment_status(services, admin, make_product, methods):
    pid = make_product(stock="0")
    sup = services.partners.save_supplier(admin, None, {"name": "Test Supplier"})
    res = services.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=date.today(),
        lines=[PurchaseLineRequest(pid, D("10"), D("10"))]), complete=True)
    pid_ = res["purchase_id"]
    services.purchases.record_payment(admin, pid_, methods[PaymentKind.BANK_TRANSFER], "40",
                                      reference="NEFT-REF-1")
    assert services.purchases.get_purchase(admin, pid_)["payment_status"] == "PARTIAL"
    with pytest.raises(ValidationError):
        services.purchases.record_payment(admin, pid_, methods[PaymentKind.CASH], "61")
    services.purchases.record_payment(admin, pid_, methods[PaymentKind.CASH], "60")
    assert services.purchases.get_purchase(admin, pid_)["payment_status"] == "PAID"


def test_sale_decreases_stock(services, admin, make_product, sell):
    pid = make_product(stock="10")
    sell([(pid, 3)])
    assert stock_of(services, admin, pid) == D("7")
    rows, _ = services.inventory.movements(admin, product_id=pid, movement_type="SALE")
    assert rows[0]["quantity"] == D("-3") and rows[0]["balance_after"] == D("7")


def test_adjustment_in_out_and_count(services, admin, make_product):
    pid = make_product(stock="10")
    services.inventory.adjust_stock(admin, pid, direction="IN", quantity="5", reason="Found")
    assert stock_of(services, admin, pid) == D("15")
    services.inventory.adjust_stock(admin, pid, direction="OUT", quantity="2", reason="Damaged")
    assert stock_of(services, admin, pid) == D("13")
    services.inventory.adjust_stock(admin, pid, direction="SET", quantity="11", reason="Count")
    assert stock_of(services, admin, pid) == D("11")
    with pytest.raises(ValidationError):
        services.inventory.adjust_stock(admin, pid, direction="IN", quantity="1", reason="")
    with pytest.raises(InsufficientStock):
        services.inventory.adjust_stock(admin, pid, direction="OUT", quantity="99", reason="x")
    assert services.inventory.verify_ledger() == []


def test_insufficient_stock_blocked(services, admin, make_product, sell):
    pid = make_product(stock="5")
    with pytest.raises(InsufficientStock, match="Insufficient stock"):
        sell([(pid, 6)])
    assert stock_of(services, admin, pid) == D("5")
    # same product split across two cart lines is aggregated
    with pytest.raises(InsufficientStock):
        sell([(pid, 3), (pid, 3)])


def test_negative_stock_configurable(services, admin, make_product, sell):
    pid = make_product(stock="1")
    services.settings.update(admin, {"allow_negative_stock": True})
    sell([(pid, 3)])
    assert stock_of(services, admin, pid) == D("-2")


def test_fractional_quantity_rules(services, admin, make_product, sell):
    whole = make_product(stock="10")
    with pytest.raises(ValidationError):
        sell([(whole, "1.5")])
    frac = make_product(stock="10", allow_fractional_qty=True, unit="m")
    sell([(frac, "2.25")])
    assert stock_of(services, admin, frac) == D("7.75")


def test_low_stock(services, admin, make_product):
    a = make_product(stock="2", min_stock_level="5")
    make_product(stock="50", min_stock_level="5")
    low = services.inventory.stock_levels(admin, low_only=True)
    assert [r["id"] for r in low] == [a]
    assert services.inventory.summary()["low_stock"] == 1


# ------------------------------------------------------------------- POS -------
def test_sale_totals_tax_and_discount(services, admin, make_product, taxes, methods):
    a = make_product(price="100", tax_id=taxes["Test GST 12"])           # exclusive
    b = make_product(price="105", tax_id=taxes["Test GST 5"], inclusive=True)
    req = SaleRequest(lines=[SaleLineRequest(a, D("2"), discount_amount=D("20")),
                             SaleLineRequest(b, D("1"))],
                      payments=[PaymentRequest(methods[PaymentKind.CASH], D("306.60"))])
    res = services.sales.create_sale(admin, req)
    sale = services.sales.get_sale(admin, res["sale_id"])
    # line A: 200 - 20 = 180 taxable, 21.60 tax ; line B: 100 taxable, 5 tax
    assert sale["taxable_total"] == D("280.00")
    assert sale["tax_total"] == D("26.60")
    assert sale["grand_total"] == D("306.60")
    assert sale["item_discount_total"] == D("20.00")
    assert sale["cgst_total"] + sale["sgst_total"] == sale["tax_total"]


def test_sale_uses_database_price_not_client(services, admin, make_product, methods):
    pid = make_product(price="100")
    with pytest.raises(ValidationError, match="does not match"):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"))],
            payments=[PaymentRequest(methods[PaymentKind.CASH], D("1.00"))]))


# ---------------------------------------------------------------- payments ------
@pytest.mark.parametrize("kind", [PaymentKind.CASH, PaymentKind.UPI, PaymentKind.DEBIT_CARD,
                                  PaymentKind.CREDIT_CARD, PaymentKind.BANK_TRANSFER,
                                  PaymentKind.OTHER])
def test_each_payment_method(services, admin, make_product, methods, kind):
    pid = make_product(price="250")
    ref = None if kind == PaymentKind.CASH else f"REF-{kind}"
    desc = "Gift voucher" if kind == PaymentKind.OTHER else None
    res = services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"))],
        payments=[PaymentRequest(methods[kind], D("250"), reference=ref, description=desc)]))
    pay = services.sales.get_sale(admin, res["sale_id"])["payments"]
    assert len(pay) == 1 and pay[0]["amount"] == D("250.00")
    assert pay[0]["reference"] == (ref or "")
    if kind == PaymentKind.OTHER:
        assert pay[0]["description"] == "Gift voucher"


def test_cash_reference_is_not_stored(services, admin, make_product, methods):
    pid = make_product(price="10")
    res = services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("10"), reference="ignored")]))
    assert services.sales.get_sale(admin, res["sale_id"])["payments"][0]["reference"] == ""


def test_other_requires_description(services, admin, make_product, methods):
    pid = make_product(price="10")
    with pytest.raises(ValidationError, match="describe"):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"))],
            payments=[PaymentRequest(methods[PaymentKind.OTHER], D("10"))]))


def test_card_number_rejected_as_reference(services, admin, make_product, methods):
    pid = make_product(price="10")
    with pytest.raises(ValidationError, match="card number"):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"))],
            payments=[PaymentRequest(methods[PaymentKind.CREDIT_CARD], D("10"),
                                     reference="4111 1111 1111 1111")]))


def test_split_payment(services, admin, make_product, methods):
    pid = make_product(price="1000")
    res = services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("400")),
                  PaymentRequest(methods[PaymentKind.UPI], D("600"), reference="UPI123")]))
    pays = services.sales.get_sale(admin, res["sale_id"])["payments"]
    assert [(p["method"], p["amount"]) for p in pays] == [("Cash", D("400.00")),
                                                         ("UPI", D("600.00"))]


@pytest.mark.parametrize("amounts", [["400", "500"], ["400", "700"], ["-100", "1100"], ["0", "1000"]])
def test_invalid_payment_totals_rejected(services, admin, make_product, methods, amounts):
    pid = make_product(price="1000")
    with pytest.raises(ValidationError):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"))],
            payments=[PaymentRequest(methods[PaymentKind.CASH], D(amounts[0])),
                      PaymentRequest(methods[PaymentKind.UPI], D(amounts[1]))]))
    assert stock_of(services, admin, pid) == D("10")


# ---------------------------------------------------------------- invoices ------
def test_invoice_numbers_unique_and_sequential(services, admin, make_product, sell):
    pid = make_product(stock="20")
    nos = [sell([(pid, 1)])["invoice_no"] for _ in range(3)]
    assert nos == ["T-000001", "T-000002", "T-000003"]


def test_invoice_number_not_reused_after_failed_sale(services, admin, make_product, sell):
    pid = make_product(stock="2")
    assert sell([(pid, 1)])["invoice_no"] == "T-000001"
    with pytest.raises(InsufficientStock):
        sell([(pid, 5)])
    # failed sale rolled back entirely, including the sequence increment
    assert sell([(pid, 1)])["invoice_no"] == "T-000002"


def test_invoice_numbering_cannot_go_backwards(services, admin, make_product, sell):
    pid = make_product(stock="5")
    sell([(pid, 1)])
    sell([(pid, 1)])
    with pytest.raises(ValidationError):
        services.settings.update(admin, {"next_invoice_number": 2})
    services.settings.update(admin, {"next_invoice_number": 100})
    assert sell([(pid, 1)])["invoice_no"] == "T-000100"


# ---------------------------------------------------------------- void --------
def test_void_sale_restores_stock(services, admin, make_product, sell):
    pid = make_product(stock="10")
    res = sell([(pid, 4)])
    services.sales.void_sale(admin, res["sale_id"], "Customer cancelled")
    assert stock_of(services, admin, pid) == D("10")
    sale = services.sales.get_sale(admin, res["sale_id"])
    assert sale["status"] == "VOIDED" and all(p["is_void"] for p in sale["payments"])
    with pytest.raises(ValidationError):
        services.sales.void_sale(admin, res["sale_id"], "again")


# --------------------------------------------------------------- integrity -----
def test_sale_rollback_on_failure_leaves_nothing(services, admin, make_product, methods,
                                                 monkeypatch):
    pid = make_product(stock="10", price="10")
    import app.services.sales_service as ss

    def boom(*a, **k):
        raise RuntimeError("simulated failure after stock update")
    real = ss.audit_service.record
    monkeypatch.setattr(ss.audit_service, "record", boom)
    with pytest.raises(RuntimeError):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, D("2"))],
            payments=[PaymentRequest(methods[PaymentKind.CASH], D("20"))]))
    monkeypatch.setattr(ss.audit_service, "record", real)
    with services.db.session() as s:
        assert s.scalar(select(Sale.id)) is None
        assert s.scalar(select(SaleItem.id)) is None
        assert s.scalar(select(Payment.id)) is None
        assert s.scalar(select(InventoryMovement.id).where(
            InventoryMovement.movement_type == "SALE")) is None
    assert stock_of(services, admin, pid) == D("10")
    assert services.settings.get("next_invoice_number") == 1


def test_financial_records_cannot_be_deleted(services, admin, make_product, sell):
    pid = make_product()
    sell([(pid, 1)])
    for table in ("sales", "sale_items", "payments", "inventory_movements", "audit_logs"):
        with pytest.raises(Exception):
            with services.db.session() as s:
                s.execute(text(f"DELETE FROM {table}"))
    with pytest.raises(Exception):
        with services.db.session() as s:
            s.execute(text("UPDATE audit_logs SET action='X'"))
    with pytest.raises(Exception):
        with services.db.session() as s:
            s.execute(text("UPDATE sales SET grand_total = 1"))
