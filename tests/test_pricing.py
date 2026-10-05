from decimal import Decimal as D

import pytest

from app.config.constants import TaxMode
from app.services.errors import ValidationError
from app.services.pricing import CartLineInput, compute_cart


def line(price, q, rate="0", inclusive=False, **kw):
    return CartLineInput(product_id=1, name="x", unit_price=D(price), quantity=D(q),
                         tax_rate=D(rate), price_includes_tax=inclusive, **kw)


def test_simple_exclusive_tax():
    r = compute_cart([line("100", "2", "12")])
    assert r.gross_total == D("200.00")
    assert r.taxable_total == D("200.00")
    assert r.tax_total == D("24.00")
    assert r.cgst_total == D("12.00") and r.sgst_total == D("12.00")
    assert r.grand_total == D("224.00")


def test_inclusive_tax_back_calculation():
    r = compute_cart([line("105", "1", "5", inclusive=True)])
    assert r.taxable_total == D("100.00")
    assert r.tax_total == D("5.00")
    assert r.grand_total == D("105.00")


def test_inter_state_igst():
    r = compute_cart([line("100", "1", "18")], tax_mode=TaxMode.INTER)
    assert r.igst_total == D("18.00") and r.cgst_total == 0 and r.sgst_total == 0


def test_item_discount_amount_and_percent():
    r = compute_cart([line("100", "2", discount_amount=D("15")),
                      line("50", "1", discount_percent=D("10"))])
    assert r.item_discount_total == D("20.00")
    assert r.grand_total == D("230.00")


def test_bill_discount_allocated_exactly():
    r = compute_cart([line("33.33", "1", "5"), line("33.33", "1", "12"), line("33.34", "1")],
                     bill_discount_amount=D("10"))
    assert sum(lr.bill_share for lr in r.lines) == D("10.00")
    assert r.grand_total == sum(lr.total for lr in r.lines)
    assert r.taxable_total == D("90.00")


def test_bill_discount_percent():
    r = compute_cart([line("200", "1")], bill_discount_percent=D("25"))
    assert r.bill_discount == D("50.00") and r.grand_total == D("150.00")


def test_discount_cannot_exceed_amount():
    with pytest.raises(ValidationError):
        compute_cart([line("10", "1", discount_amount=D("11"))])
    with pytest.raises(ValidationError):
        compute_cart([line("10", "1")], bill_discount_amount=D("10.01"))


def test_invalid_quantity():
    with pytest.raises(ValidationError):
        compute_cart([line("10", "0")])
    with pytest.raises(ValidationError):
        compute_cart([line("10", "-1")])


def test_round_off():
    r = compute_cart([line("99.60", "1")], round_off=True)
    assert r.grand_total == D("100") and r.round_off == D("0.40")


def test_cgst_sgst_split_odd_paisa():
    r = compute_cart([line("0.10", "1", "5")])
    assert r.tax_total == D("0.01")
    assert r.cgst_total + r.sgst_total == r.tax_total
