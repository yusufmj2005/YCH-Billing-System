from decimal import Decimal

import pytest

from app.services.errors import ValidationError
from tests.conftest import stock_of


def test_create_and_get_product(services, admin, taxes):
    pid = services.catalog.create_product(admin, {
        "name": "Test Item", "sku": "SKU-1", "barcode": "BC-0001", "selling_price": "250.00",
        "purchase_price": "180", "unit": "pcs", "tax_rate_id": taxes["Test GST 5"],
        "opening_stock": "7"})
    p = services.catalog.get_product(admin, pid)
    assert p["name"] == "Test Item"
    assert p["selling_price"] == Decimal("250.00")
    assert p["current_stock"] == Decimal("7")
    assert p["tax_rate"] == Decimal("5")
    # opening stock produced a ledger movement
    rows, total = services.inventory.movements(admin, product_id=pid)
    assert total == 1 and rows[0]["movement_type"] == "ADJUSTMENT_IN"


def test_edit_product(services, admin, make_product):
    pid = make_product()
    data = services.catalog.get_product(admin, pid)
    data.update(name="Renamed", selling_price="120.50")
    services.catalog.update_product(admin, pid, data)
    p = services.catalog.get_product(admin, pid)
    assert p["name"] == "Renamed" and p["selling_price"] == Decimal("120.50")
    assert stock_of(services, admin, pid) == Decimal("10")  # editing never changes stock


def test_search_products(services, admin, make_product):
    make_product(name="Alpha Widget", barcode="111")
    make_product(name="Beta Gadget", barcode="222")
    rows, total = services.catalog.list_products(admin, search="widget")
    assert total == 1 and rows[0]["name"] == "Alpha Widget"
    assert services.catalog.find_by_code(admin, "222")["name"] == "Beta Gadget"
    assert services.catalog.find_by_code(admin, "does-not-exist") is None


def test_duplicate_sku_rejected(services, admin, make_product):
    make_product(sku="DUP-1")
    with pytest.raises(ValidationError, match="SKU"):
        make_product(sku="dup-1")  # case-insensitive


def test_duplicate_sku_allowed_when_not_unique(services, admin, make_product):
    services.settings.update(admin, {"sku_unique": False})
    make_product(sku="DUP-2")
    make_product(sku="DUP-2")


def test_duplicate_barcode_rejected(services, admin, make_product):
    make_product(barcode="8901234567890")
    with pytest.raises(ValidationError, match="Barcode"):
        make_product(barcode="8901234567890")


def test_deactivate_product_hidden_from_pos(services, admin, make_product):
    pid = make_product(barcode="ZZ1")
    services.catalog.set_product_active(admin, pid, False)
    assert services.catalog.find_by_code(admin, "ZZ1") is None
    rows, _ = services.catalog.list_products(admin, status="inactive")
    assert [r["id"] for r in rows] == [pid]


def test_generate_barcode_unique_and_ean13_valid(services, admin):
    from app.barcode.codes import is_valid_ean13
    a = services.catalog.generate_barcode(admin)
    b = services.catalog.generate_barcode(admin)
    assert a != b
    services.settings.update(admin, {"barcode_symbology": "EAN13", "barcode_prefix": "29"})
    code = services.catalog.generate_barcode(admin)
    assert code.startswith("29") and is_valid_ean13(code)


def test_category_management(services, admin):
    cats = [c["name"] for c in services.catalog.list_categories()]
    assert "Yarn" in cats and "Handmade Products" in cats
    cid = services.catalog.save_category(admin, None, {"name": "Patterns"})
    assert "Patterns" in [c["name"] for c in services.catalog.list_categories()]
    with pytest.raises(ValidationError):
        services.catalog.save_category(admin, None, {"name": "patterns"})
    services.catalog.save_category(admin, cid, {"name": "Patterns", "is_active": False})
    assert "Patterns" not in [c["name"] for c in services.catalog.list_categories()]


def test_invalid_tax_rate_rejected(services, admin):
    with pytest.raises(ValidationError):
        services.catalog.save_tax_rate(admin, None, {"name": "Bad", "rate": "150"})
    with pytest.raises(ValidationError):
        services.catalog.save_tax_rate(admin, None, {"name": "Bad", "rate": "-1"})
