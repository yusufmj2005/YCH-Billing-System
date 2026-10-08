import sqlite3
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.bootstrap import build_services
from app.config.constants import PaymentKind
from app.printing.invoice_pdf import build_invoice_pdf, build_return_pdf
from app.printing.label_pdf import LABEL_LAYOUTS, build_labels_pdf
from app.reports.exporters import export_csv, export_pdf
from app.services.errors import ValidationError
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest
from app.utils.words import amount_in_words
from tests.conftest import ADMIN_PASSWORD


# ---------------------------------------------------------------- PDFs ---------
@pytest.mark.parametrize("paper", ["A4", "RECEIPT_80MM"])
def test_invoice_pdf_generated(services, admin, make_product, taxes, methods, tmp_path, paper):
    pid = make_product(price="499.50", tax_id=taxes["Test GST 12"])
    res = services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("2"), discount_amount=D("9.50"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("500")),
                  PaymentRequest(methods[PaymentKind.UPI], D("608.24"), reference="UPI-REF")]))
    sale = services.sales.get_sale(admin, res["sale_id"])
    assert sale["grand_total"] == D("1108.24")  # (999 - 9.50) x 1.12
    out = build_invoice_pdf(sale, services.settings.get_all(), tmp_path / "inv.pdf", paper=paper)
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 1500


def test_return_pdf_and_labels(services, admin, make_product, methods, tmp_path, sell):
    pid = make_product(price="20", barcode="8901030865278")
    res = sell([(pid, 2)])
    sale = services.sales.get_sale(admin, res["sale_id"])
    r = services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(sale["items"][0]["id"], D("1"))],
        reason="Wrong colour", refunds=[PaymentRequest(methods[PaymentKind.CASH], D("20"))]))
    out = build_return_pdf(services.returns.get_return(admin, r["return_id"]),
                           services.settings.get_all(), tmp_path / "ret.pdf")
    assert out.read_bytes().startswith(b"%PDF")
    for layout in LABEL_LAYOUTS:
        lab = build_labels_pdf([{"name": "Label test", "barcode": "8901030865278", "price": D("20"),
                                 "copies": 3},
                                {"name": "Code128", "barcode": "ABC-123", "price": D("5"),
                                 "copies": 1}],
                               tmp_path / "labels.pdf", layout, services.settings.get_all())
        assert lab.read_bytes().startswith(b"%PDF")


def test_amount_in_words():
    assert amount_in_words(D("1107.12")) == \
        "Rupees One Thousand One Hundred Seven and Twelve Paise Only"
    assert amount_in_words(D("2500000")) == "Rupees Twenty Five Lakh Only"


# --------------------------------------------------------------- backup --------
def test_backup_and_restore(services, admin, make_product, sell, tmp_path):
    pid = make_product(stock="10")
    sell([(pid, 1)])
    backup = services.backup.create_backup(admin, tmp_path / "bk")
    info = services.backup.validate_backup(backup)
    assert info["counts"]["sales"] == 1 and info["business_name"] == "Test Business"

    sell([(pid, 2)])  # change after the backup
    assert services.sales.list_sales(admin)[1] == 2

    safety = services.backup.restore(admin, backup)
    assert safety.exists()
    assert services.sales.list_sales(admin)[1] == 1
    assert services.catalog.get_product(admin, pid)["current_stock"] == D("9")
    # the safety backup contains the post-backup state
    assert services.backup.validate_backup(safety)["counts"]["sales"] == 2
    # login still works after restore
    services.auth.login("admin", ADMIN_PASSWORD)


def test_invalid_backup_rejected(services, admin, tmp_path):
    bogus = tmp_path / "not-a-db.db"
    bogus.write_bytes(b"this is not sqlite")
    with pytest.raises(ValidationError):
        services.backup.validate_backup(bogus)
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE x (a)")
    con.commit()
    con.close()
    with pytest.raises(ValidationError):
        services.backup.restore(admin, other)


def test_auto_backup_once_per_day(services, admin):
    first = services.backup.auto_backup_if_due(keep=5)
    assert first is not None
    assert services.backup.auto_backup_if_due(keep=5) is None


# ------------------------------------------------------------ persistence -----
def test_reopen_existing_database_preserves_data(tmp_path, services, admin, make_product, sell):
    """Simulates an application update: a new process opens the existing DB."""
    pid = make_product(stock="5")
    sell([(pid, 2)])
    services.db.dispose()
    again = build_services(services.paths)
    assert again.settings.get("business_name") == "Test Business"
    assert again.settings.is_setup_completed()
    cu = again.auth.login("admin", ADMIN_PASSWORD)
    assert again.sales.list_sales(cu)[1] == 1
    assert again.catalog.get_product(cu, pid)["current_stock"] == D("3")
    again.db.dispose()


def test_migration_runner_upgrades_old_schema(tmp_path, services, admin, monkeypatch):
    """A database stamped with an older version gets backed up and migrated."""
    from app.database import migrations
    from app.config import constants
    services.db.dispose()
    calls = []
    nxt = constants.SCHEMA_VERSION + 1
    monkeypatch.setattr(constants, "SCHEMA_VERSION", nxt)
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", nxt)
    monkeypatch.setitem(migrations.MIGRATIONS, nxt, lambda conn: calls.append(
        conn.exec_driver_sql("ALTER TABLE customers ADD COLUMN test_col TEXT")))
    again = build_services(services.paths)
    assert calls
    meta = migrations.read_meta(again.db)
    assert meta["schema_version"] == str(nxt)
    assert any("pre-upgrade" in b["name"] for b in again.backup.list_backups())
    again.db.dispose()


def test_newer_database_refused(tmp_path, services, admin):
    from app.database.migrations import SchemaError
    services.db.dispose()
    con = sqlite3.connect(services.paths.database_file)
    con.execute("UPDATE app_meta SET value='999' WHERE key='schema_version'")
    con.commit()
    con.close()
    with pytest.raises(SchemaError):
        build_services(services.paths)


# -------------------------------------------------------------- reports --------
def test_reports_and_profit_loss(services, admin, make_product, taxes, methods, tmp_path):
    pid = make_product(stock="10", price="112", cost="50", tax_id=taxes["Test GST 12"],
                       inclusive=True)
    res = services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("2"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("100")),
                  PaymentRequest(methods[PaymentKind.UPI], D("124"), reference="U1")]))
    sale = services.sales.get_sale(admin, res["sale_id"])
    services.returns.create_return(admin, ReturnRequest(
        sale_id=sale["id"], lines=[ReturnLineRequest(sale["items"][0]["id"], D("1"))],
        reason="x", refunds=[PaymentRequest(methods[PaymentKind.CASH], D("112"))]))
    cats = {c["name"]: c["id"] for c in services.expenses.list_categories()}
    services.expenses.create_expense(admin, {"category_id": cats["Rent"], "amount": "30",
                                             "expense_date": date.today(),
                                             "payment_method_id": methods[PaymentKind.CASH]})
    today = date.today()
    pl = services.reports.profit_loss(admin, today, today)
    vals = {r["item"]: r["amount"] for r in pl.rows}
    assert vals["Net sales (revenue)"] == D("100.00")       # 200 taxable - 100 returned
    assert vals["Less: cost of goods sold"] == D("-50.00")  # 100 cost - 50 restocked
    assert vals["Gross profit"] == D("50.00")
    assert vals["NET PROFIT / (LOSS)"] == D("20.00")

    pm = services.reports.payment_method_sales(admin, today, today)
    by = {r["method"]: r for r in pm.rows}
    assert by["Cash"]["received"] == D("100.00") and by["Cash"]["refunded"] == D("112.00")
    assert by["UPI"]["net"] == D("124.00")

    summary = services.reports.payment_summary(admin, today, today)
    cash = next(r for r in summary.rows if r["method"] == "Cash")
    assert cash["net"] == D("100") - D("112") - D("30")

    for period in ("day", "week", "month"):
        r = services.reports.sales_summary(admin, today - timedelta(days=40), today, period)
        assert r.totals["total"] == D("224.00") and r.totals["refunds"] == D("112.00")

    tax = services.reports.tax_summary(admin, today, today)
    assert tax.totals["tax"] == D("12.00")  # 24 collected - 12 returned

    for rep in (services.reports.product_sales(admin, today, today),
                services.reports.category_sales(admin, today, today),
                services.reports.sales_register(admin, today, today),
                services.reports.current_stock(admin),
                services.reports.current_stock(admin, low_only=True),
                services.reports.inventory_valuation(admin),
                services.reports.stock_movement(admin, today, today),
                services.reports.purchase_register(admin, today, today),
                services.reports.supplier_purchases(admin, today, today),
                services.reports.product_purchases(admin, today, today),
                services.reports.expense_register(admin, today, today),
                services.reports.expense_by_category(admin, today, today),
                services.reports.revenue_summary(admin, today, today), pl, pm, summary, tax):
        assert export_csv(rep, tmp_path / "r.csv").stat().st_size > 0
        assert export_pdf(rep, tmp_path / "r.pdf", "Test Business").read_bytes()[:4] == b"%PDF"

    dash = services.dashboard.overview(admin, today, today)
    assert dash["sales_total"] == D("224.00") and dash["sales_count"] == 1
    assert dash["expenses"] == D("30.00")
    assert dash["inventory_value"] == D("450.00")  # 9 x 50


def test_empty_dashboard_shows_zero(services, admin):
    d = services.dashboard.overview(admin, date.today(), date.today())
    assert d["sales_total"] == 0 and d["sales_count"] == 0 and d["expenses"] == 0
    assert d["inventory_value"] == 0 and d["recent_sales"] == []
    assert all(v == 0 for _, v in d["trend"])


# -------------------------------------------------------- expenses & staff ----
def test_expenses_and_void(services, admin, methods):
    cats = {c["name"]: c["id"] for c in services.expenses.list_categories()}
    assert set(cats) >= {"Rent", "Salaries", "Electricity", "Internet", "Packaging",
                         "Transport", "Marketing", "Other Expenses"}
    eid = services.expenses.create_expense(admin, {
        "category_id": cats["Internet"], "amount": "799", "expense_date": date.today(),
        "description": "Monthly plan"})
    rows, total, amount = services.expenses.list_expenses(admin)
    assert total == 1 and amount == D("799")
    with pytest.raises(ValidationError):
        services.expenses.create_expense(admin, {"category_id": cats["Rent"], "amount": "-5",
                                                 "expense_date": date.today()})
    services.expenses.void_expense(admin, eid, "Duplicate")
    rows, total, amount = services.expenses.list_expenses(admin)
    assert total == 0 and amount == 0


def test_staff_flow(services, admin, methods):
    emp = services.staff.save_employee(admin, None, {"employee_code": "E-1", "name": "Test Emp",
                                                     "joining_date": date.today()})
    services.staff.save_attendance(admin, emp, date.today(), {"status": "Present",
                                                              "check_in": "09:30",
                                                              "check_out": "18:00"})
    rows = services.staff.attendance_for_date(admin, date.today())
    assert rows[0]["status"] == "Present"
    with pytest.raises(ValidationError):
        services.staff.save_attendance(admin, emp, date.today(), {"status": "Present",
                                                                  "check_in": "18:00",
                                                                  "check_out": "09:00"})
    lt = services.staff.save_leave_type(admin, None, {"name": "Test Leave"})
    lid = services.staff.create_leave(admin, {"employee_id": emp, "leave_type_id": lt,
                                              "start_date": date.today(),
                                              "end_date": date.today() + timedelta(days=1)})
    services.staff.decide_leave(admin, lid, True)
    assert services.staff.list_leave(admin)[0]["status"] == "Approved"
    with pytest.raises(ValidationError):
        services.staff.decide_leave(admin, lid, False)
    pr = services.staff.create_payroll(admin, {"employee_id": emp, "period_start": date(2026, 9, 1),
                                               "period_end": date(2026, 9, 30),
                                               "base_salary": "1000", "allowances": "100",
                                               "deductions": "50"})
    assert services.staff.list_payroll(admin)[0]["net_salary"] == D("1050")
    services.staff.mark_payroll_paid(admin, pr, paid_date=date.today(),
                                     payment_method_id=methods[PaymentKind.BANK_TRANSFER],
                                     reference="SAL-1", record_expense=True)
    rows, total, amount = services.expenses.list_expenses(admin)
    assert amount == D("1050") and rows[0]["from_payroll"]
    services.staff.cancel_payroll(admin, pr)
    assert services.expenses.list_expenses(admin)[2] == 0
