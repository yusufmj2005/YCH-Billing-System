from decimal import Decimal as D

import pytest

from app.config.constants import PaymentKind
from app.services.errors import ValidationError
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest
from tests.conftest import stock_of


def _sale(services, admin, sell, make_product, taxes, qty=3):
    pid = make_product(stock="10", price="112", tax_id=taxes["Test GST 12"], inclusive=True)
    res = sell([(pid, qty)])
    sale = services.sales.get_sale(admin, res["sale_id"])
    return pid, sale


def test_valid_return_updates_inventory_and_refund(services, admin, sell, make_product, taxes,
                                                  methods):
    pid, sale = _sale(services, admin, sell, make_product, taxes)
    item = sale["items"][0]
    res = services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(item["id"], D("1"))], reason="Defective",
        refunds=[PaymentRequest(methods[PaymentKind.CASH], D("112.00"))]))
    assert res["refund_total"] == D("112.00")
    assert stock_of(services, admin, pid) == D("8")  # 10 - 3 + 1
    detail = services.returns.get_return(admin, res["return_id"])
    assert detail["invoice_no"] == sale["invoice_no"]
    assert detail["refunds"][0]["amount"] == D("112.00")
    again = services.sales.get_sale(admin, sale["id"])
    assert again["items"][0]["returned_quantity"] == D("1")


def test_excess_return_blocked(services, admin, sell, make_product, taxes, methods):
    pid, sale = _sale(services, admin, sell, make_product, taxes, qty=2)
    item = sale["items"][0]
    with pytest.raises(ValidationError, match="exceeds"):
        services.returns.create_return(admin, ReturnRequest(
            sale_id=sale["id"], lines=[ReturnLineRequest(item["id"], D("3"))], reason="x",
            refunds=[PaymentRequest(methods[PaymentKind.CASH], D("336"))]))
    services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(item["id"], D("2"))], reason="x",
        refunds=[PaymentRequest(methods[PaymentKind.CASH], D("224"))]))
    with pytest.raises(ValidationError, match="exceeds"):
        services.returns.create_return(admin, ReturnRequest(
            sale_id=sale["id"], lines=[ReturnLineRequest(item["id"], D("1"))], reason="x",
            refunds=[PaymentRequest(methods[PaymentKind.CASH], D("112"))]))
    assert stock_of(services, admin, pid) == D("10")


def test_partial_returns_sum_to_line_total(services, admin, sell, make_product, taxes, methods):
    pid = make_product(stock="10", price="10", tax_id=taxes["Test GST 12"])
    res = sell([(pid, 3)])
    sale = services.sales.get_sale(admin, res["sale_id"])
    item = sale["items"][0]
    total = D(0)
    for _ in range(3):
        prev = services.returns.preview(admin, sale["id"], [ReturnLineRequest(item["id"], D("1"))])
        r = services.returns.create_return(admin, ReturnRequest(
            sale_id=sale["id"], lines=[ReturnLineRequest(item["id"], D("1"))], reason="x",
            refunds=[PaymentRequest(methods[PaymentKind.UPI], prev["refund_total"])]))
        total += r["refund_total"]
    assert total == item["line_total"]


def test_refund_must_match(services, admin, sell, make_product, taxes, methods):
    _, sale = _sale(services, admin, sell, make_product, taxes)
    with pytest.raises(ValidationError, match="refund total"):
        services.returns.create_return(admin, ReturnRequest(
            sale_id=sale["id"], lines=[ReturnLineRequest(sale["items"][0]["id"], D("1"))],
            reason="x", refunds=[PaymentRequest(methods[PaymentKind.CASH], D("50"))]))


def test_damaged_return_not_restocked(services, admin, sell, make_product, taxes, methods):
    pid, sale = _sale(services, admin, sell, make_product, taxes)
    services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(sale["items"][0]["id"], D("1"), False)],
        reason="Damaged", refunds=[PaymentRequest(methods[PaymentKind.CASH], D("112"))]))
    assert stock_of(services, admin, pid) == D("7")


def test_cannot_void_sale_with_returns(services, admin, sell, make_product, taxes, methods):
    _, sale = _sale(services, admin, sell, make_product, taxes)
    services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(sale["items"][0]["id"], D("1"))],
        reason="x", refunds=[PaymentRequest(methods[PaymentKind.CASH], D("112"))]))
    with pytest.raises(ValidationError):
        services.sales.void_sale(admin, sale["id"], "no")
