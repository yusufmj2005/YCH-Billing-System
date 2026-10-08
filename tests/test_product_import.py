"""Bulk product import from CSV: all-or-nothing, every error reported."""
from decimal import Decimal as D

import pytest

from app.config.constants import Perm
from app.services.errors import PermissionDenied, ValidationError
from app.services.product_import import COLUMN_NAMES, read_csv, write_template
from tests.conftest import stock_of

HEADER = ",".join(COLUMN_NAMES)


def _csv(tmp_path, lines, name="products.csv", encoding="utf-8-sig", header=HEADER):
    p = tmp_path / name
    p.write_text("\n".join([header, *lines]) + "\n", encoding=encoding)
    return p


def _row(**kw):
    vals = {c: "" for c in COLUMN_NAMES}
    vals.update(kw)
    return ",".join(str(vals[c]) for c in COLUMN_NAMES)


def _products(services, admin):
    return {p["sku"]: p for p in services.catalog.list_products(admin)[0]}


def test_template_has_every_column(tmp_path):
    rows = read_csv(write_template(tmp_path / "template.csv"))
    assert rows == []
    assert (tmp_path / "template.csv").read_text(encoding="utf-8-sig").strip() == HEADER


def test_import_creates_products_stock_and_categories(services, admin, taxes, tmp_path):
    path = _csv(tmp_path, [
        _row(name="Merino Yarn Red", sku="MY-RED", barcode="8901234567890", category="Yarn",
             unit="ball", purchase_price="120", selling_price="199", tax_rate="test gst 5",
             price_includes_tax="yes", min_stock_level="5", opening_stock="24"),
        _row(name="Cotton Thread", sku="CT-1", category="Threads", unit="m",
             selling_price="4.50", allow_fractional_qty="yes", opening_stock="150.5"),
        _row(name="Hook 4mm", sku="HK-4", unit="pcs", selling_price="85", price_includes_tax="no"),
    ])
    rows = read_csv(path)
    preview = services.product_import.import_rows(admin, rows, dry_run=True)
    assert preview.ok and preview.created == 3 and preview.new_categories == ["Threads"]
    assert _products(services, admin) == {}                      # dry run saved nothing

    res = services.product_import.import_rows(admin, rows, dry_run=False)
    assert res.ok and res.created == 3
    prods = _products(services, admin)
    red = prods["MY-RED"]
    assert red["category"] == "Yarn" and red["tax_name"] == "Test GST 5"
    assert red["selling_price"] == D("199") and red["min_stock_level"] == D("5")
    assert stock_of(services, admin, red["id"]) == D("24")
    assert stock_of(services, admin, prods["CT-1"]["id"]) == D("150.5")
    assert prods["HK-4"]["price_includes_tax"] is False
    assert "Threads" in {c["name"] for c in services.catalog.list_categories()}
    assert services.inventory.verify_ledger() == []


def test_any_bad_row_saves_nothing_and_reports_every_problem(services, admin, make_product,
                                                             tmp_path):
    make_product(barcode="EXISTING-1")
    path = _csv(tmp_path, [
        _row(name="Good", sku="G-1", unit="pcs", selling_price="10"),
        _row(name="Dup SKU", sku="G-1", unit="pcs", selling_price="10"),
        _row(name="Dup barcode", sku="G-2", barcode="EXISTING-1", unit="pcs", selling_price="1"),
        _row(name="Bad price", sku="G-3", unit="pcs", selling_price="ten"),
        _row(name="Bad tax", sku="G-4", unit="pcs", selling_price="1", tax_rate="VAT 99"),
        _row(name="Bad flag", sku="G-5", unit="pcs", selling_price="1", price_includes_tax="maybe"),
        _row(name="Half item", sku="G-6", unit="pcs", selling_price="1", opening_stock="1.5"),
        _row(name="", sku="G-7", unit="pcs", selling_price="1"),
        _row(name="No price", sku="G-8", unit="pcs"),
    ])
    before = len(_products(services, admin))
    res = services.product_import.import_rows(admin, read_csv(path), dry_run=False)
    assert not res.ok and res.created == 0
    rows_with_errors = [e.split(":")[0] for e in res.errors]
    assert rows_with_errors == [f"Row {n}" for n in range(3, 11)]
    assert "already used" in res.errors[0] and "already used" in res.errors[1]
    assert "VAT 99" in res.errors[3]
    assert len(_products(services, admin)) == before            # nothing saved
    assert services.inventory.verify_ledger() == []


def test_excel_variants_semicolon_and_ansi(services, admin, tmp_path):
    header = ";".join(COLUMN_NAMES)
    line = ";".join({"name": "Café Wool", "sku": "CW-1", "unit": "pcs",
                     "selling_price": "1,250.00"}.get(c, "") for c in COLUMN_NAMES)
    path = _csv(tmp_path, [line, ";" * (len(COLUMN_NAMES) - 1)], encoding="cp1252",
                header=header)
    res = services.product_import.import_rows(admin, read_csv(path), dry_run=False)
    assert res.ok, res.errors
    p = _products(services, admin)["CW-1"]
    assert p["name"] == "Café Wool" and p["selling_price"] == D("1250")


def test_header_problems_are_reported(tmp_path):
    with pytest.raises(ValidationError, match="Unknown column"):
        read_csv(_csv(tmp_path, [], header="name,unit,selling_price,colour"))
    with pytest.raises(ValidationError, match="Missing required column.*selling_price"):
        read_csv(_csv(tmp_path, [], header="name,unit"))
    rows = read_csv(_csv(tmp_path, ["Yarn,pcs,10"], header="Name,Unit,Selling Price"))
    assert rows == [{"name": "Yarn", "unit": "pcs", "selling_price": "10"}]


def test_import_permissions(services, admin, tmp_path):
    rows = read_csv(_csv(tmp_path, [_row(name="A", unit="pcs", selling_price="1",
                                         opening_stock="3", category="New Cat")]))
    cashier = next(r["id"] for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "cashier", "password": "Cashier-123",
                                       "role_id": cashier, "must_change_password": False})
    with pytest.raises(PermissionDenied):
        services.product_import.import_rows(services.auth.login("cashier", "Cashier-123"), rows)

    rid = services.users.save_role(admin, None, "Catalog clerk", "", [Perm.EDIT_PRODUCTS])
    services.users.create_user(admin, {"username": "clerk", "password": "Clerk-1234",
                                       "role_id": rid, "must_change_password": False})
    clerk = services.auth.login("clerk", "Clerk-1234")
    res = services.product_import.import_rows(clerk, rows, dry_run=True)
    assert not res.ok and "Adjust stock" in res.errors[0]
    rows[0]["opening_stock"] = ""
    res = services.product_import.import_rows(clerk, rows, dry_run=True)
    assert not res.ok and "may not create categories" in res.errors[0]


def test_import_dialog_check_then_import(services, admin, tmp_path, monkeypatch):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from app.ui.context import AppContext
    from app.ui.dialogs import import_dialog
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(import_dialog, "confirm", lambda *a, **k: True)
    dlg = import_dialog.ImportProductsDialog(None, AppContext(services=services, user=admin))
    bad = _csv(tmp_path, [_row(name="X", unit="pcs", selling_price="abc")], name="bad.csv")
    dlg.check_file(str(bad))
    assert not dlg.import_btn.isEnabled() and "Row 2" in dlg.report.toPlainText()
    good = _csv(tmp_path, [_row(name="X", sku="X1", unit="pcs", selling_price="5"),
                           _row(name="Y", sku="Y1", unit="pcs", selling_price="6")],
                name="good.csv")
    dlg.check_file(str(good))
    assert dlg.import_btn.isEnabled() and "Ready to import 2" in dlg.report.toPlainText()
    dlg.do_import()
    assert dlg.imported == 2 and set(_products(services, admin)) == {"X1", "Y1"}
    dlg.close()
