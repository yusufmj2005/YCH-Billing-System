"""Edge cases and regression tests found during exploratory testing."""
import os
from decimal import Decimal
from decimal import Decimal as D

import pytest

from app.config.constants import PaymentKind, Perm
from app.services.errors import BusinessError, PermissionDenied, ValidationError
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest
from tests.conftest import ADMIN_PASSWORD, stock_of

PASSWORD = "Edge-Case-123"


def _role_id(services, admin, name=None, system=False):
    return next(r["id"] for r in services.users.list_roles(admin)
                if (r["is_system"] if system else r["name"] == name))


def _user_manager(services, admin):
    """A non-administrator holding only MANAGE_USERS."""
    rid = services.users.save_role(admin, None, "Supervisor", "", [Perm.MANAGE_USERS])
    services.users.create_user(admin, {"username": "supervisor", "password": PASSWORD,
                                       "role_id": rid, "must_change_password": False})
    return services.auth.login("supervisor", PASSWORD)


def _second_admin(services, admin):
    return services.users.create_user(admin, {
        "username": "admin2", "password": PASSWORD,
        "role_id": _role_id(services, admin, system=True), "must_change_password": False})


# ---- users & auth ----------------------------------------------------------------
def test_non_admin_cannot_deactivate_admin(services, admin):
    sup = _user_manager(services, admin)
    admin2 = _second_admin(services, admin)
    with pytest.raises(ValidationError):
        services.users.update_user(sup, admin2, {"is_active": False})
    # an administrator still can
    services.users.update_user(admin, admin2, {"is_active": False})


def test_non_admin_cannot_reset_admin_password(services, admin):
    sup = _user_manager(services, admin)
    admin2 = _second_admin(services, admin)
    with pytest.raises(ValidationError):
        services.users.reset_password(sup, admin2, "Whatever-123")


def test_username_unique_ignoring_case(services, admin):
    with pytest.raises(ValidationError):
        services.users.create_user(admin, {"username": "ADMIN", "password": PASSWORD,
                                           "role_id": _role_id(services, admin, "Cashier")})


def test_deactivated_user_cannot_reload_session(services, admin):
    uid = services.users.create_user(admin, {
        "username": "cashier", "password": PASSWORD,
        "role_id": _role_id(services, admin, "Cashier"), "must_change_password": False})
    cu = services.auth.login("cashier", PASSWORD)
    services.users.update_user(admin, uid, {"is_active": False})
    with pytest.raises(BusinessError):
        services.auth.reload(cu)


def test_lockout_blocks_correct_password(services, admin):
    for _ in range(5):
        with pytest.raises(BusinessError):
            services.auth.login("admin", "wrong-password")
    with pytest.raises(BusinessError, match="locked"):
        services.auth.login("admin", ADMIN_PASSWORD)


def test_cashier_permission_boundaries(services, admin, make_product, sell):
    services.users.create_user(admin, {
        "username": "cashier", "password": PASSWORD,
        "role_id": _role_id(services, admin, "Cashier"), "must_change_password": False})
    cu = services.auth.login("cashier", PASSWORD)
    pid = make_product()
    res = sell([(pid, 1)])
    with pytest.raises(PermissionDenied):
        services.sales.void_sale(cu, res["sale_id"], "x")
    with pytest.raises(PermissionDenied):
        services.inventory.adjust_stock(cu, pid, direction="IN", quantity="5", reason="x")
    with pytest.raises(PermissionDenied):
        services.settings.update(cu, {"allow_negative_stock": True})


# ---- input validation ------------------------------------------------------------
@pytest.mark.parametrize("bad", ["NaN", "abc", "-5", "150"])
def test_invalid_line_discount_percent(services, admin, make_product, methods, bad):
    pid = make_product()
    with pytest.raises(ValidationError):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, Decimal(1), discount_percent=bad)],
            payments=[PaymentRequest(methods[PaymentKind.CASH], Decimal("100"))]))


@pytest.mark.parametrize("bad", ["NaN", "abc", "-1", "101"])
def test_invalid_bill_discount_percent(services, admin, make_product, methods, bad):
    pid = make_product()
    with pytest.raises(ValidationError):
        services.sales.create_sale(admin, SaleRequest(
            lines=[SaleLineRequest(pid, Decimal(1))], bill_discount_percent=bad,
            payments=[PaymentRequest(methods[PaymentKind.CASH], Decimal("100"))]))


@pytest.mark.parametrize("bad", ["1e400", "Infinity", "9" * 40, "1e30"])
def test_huge_amounts_rejected(services, admin, bad):
    with pytest.raises(ValidationError):
        services.catalog.create_product(admin, {"name": "x", "selling_price": bad, "unit": "pcs"})


# ---- returns ---------------------------------------------------------------------
def test_partial_returns_add_up_to_line_total(services, admin, make_product, sell, methods,
                                              taxes):
    pid = make_product(price="33.33", stock="10", tax_id=taxes["Test GST 12"], inclusive=True)
    res = sell([(pid, 3)])
    item = services.sales.get_sale(admin, res["sale_id"])["items"][0]
    line = [ReturnLineRequest(item["id"], Decimal(1))]
    refunded = Decimal(0)
    for _ in range(3):
        refund = services.returns.preview(admin, res["sale_id"], line)["refund_total"]
        services.returns.create_return(admin, ReturnRequest(
            res["sale_id"], line, "edge case",
            [PaymentRequest(methods[PaymentKind.CASH], refund)]))
        refunded += refund
    assert refunded == item["line_total"]
    assert stock_of(services, admin, pid) == Decimal(10)
    with pytest.raises(ValidationError):
        services.returns.preview(admin, res["sale_id"], line)


def _return(services, admin, methods, sale_id, item_id, qty):
    line = [ReturnLineRequest(item_id, Decimal(qty))]
    refund = services.returns.preview(admin, sale_id, line)["refund_total"]
    return services.returns.create_return(admin, ReturnRequest(
        sale_id, line, "edge case", [PaymentRequest(methods[PaymentKind.CASH], refund)]))


@pytest.mark.parametrize("price, paid, round_off", [
    ("100.40", "100", "-0.40"),   # rounded down: must not refund 100.40
    ("99.60", "100", "0.40"),     # rounded up: customer gets back the full 100
    ("100.00", "100", "0.00"),
])
def test_full_return_refunds_exactly_what_was_paid(services, admin, make_product, sell, methods,
                                                   price, paid, round_off):
    services.settings.update(admin, {"round_off_total": True})
    pid = make_product(price=price, stock="5")
    res = sell([(pid, 1)])
    assert res["grand_total"] == Decimal(paid)
    item = services.sales.get_sale(admin, res["sale_id"])["items"][0]
    ret = _return(services, admin, methods, res["sale_id"], item["id"], 1)
    assert ret["refund_total"] == Decimal(paid)
    detail = services.returns.get_return(admin, ret["return_id"])
    assert detail["round_off"] == Decimal(round_off)
    assert detail["refund_total"] == (detail["taxable_total"] + detail["tax_total"]
                                      + detail["round_off"])


def test_round_off_refunded_only_by_the_completing_return(services, admin, make_product, sell,
                                                          methods, taxes):
    services.settings.update(admin, {"round_off_total": True})
    a = make_product(price="10.30", stock="10", tax_id=taxes["Test GST 12"], inclusive=True)
    b = make_product(price="5.15", stock="10")
    res = sell([(a, 2), (b, 1)])                    # 25.75 -> paid 26
    sale = services.sales.get_sale(admin, res["sale_id"])
    assert sale["round_off"] == Decimal("0.25")
    ia, ib = (it["id"] for it in sale["items"])
    r1 = _return(services, admin, methods, res["sale_id"], ia, 1)
    r2 = _return(services, admin, methods, res["sale_id"], ib, 1)
    r3 = _return(services, admin, methods, res["sale_id"], ia, 1)  # completes the invoice
    rounds = [services.returns.get_return(admin, r["return_id"])["round_off"] for r in (r1, r2, r3)]
    assert rounds == [Decimal(0), Decimal(0), Decimal("0.25")]
    assert sum(r["refund_total"] for r in (r1, r2, r3)) == res["grand_total"]


def test_profit_loss_is_zero_after_full_return_of_rounded_sale(services, admin, make_product,
                                                               sell, methods):
    from datetime import date
    services.settings.update(admin, {"round_off_total": True})
    pid = make_product(price="100.40", cost="60", stock="5")
    res = sell([(pid, 1)])
    item = services.sales.get_sale(admin, res["sale_id"])["items"][0]
    _return(services, admin, methods, res["sale_id"], item["id"], 1)
    with services.db.session() as s:
        f = services.reports.profit_loss_figures(s, date.today(), date.today())
    assert f["net_sales"] == 0
    assert f["round_off"] == 0
    assert f["gross_profit"] == 0
    assert f["refund_total"] == f["sales_total"] == Decimal("100")


# ---- settings --------------------------------------------------------------------
def test_invoice_prefix_wildcard_chars_are_literal(services, admin, make_product, sell):
    pid = make_product()
    services.settings.update(admin, {"invoice_prefix": "AB"})
    sell([(pid, 1)])
    # "A_" is a different prefix; "_" must not act as a LIKE wildcard matching "AB…".
    services.settings.update(admin, {"invoice_prefix": "A_", "next_invoice_number": 1})


# ---- backup ----------------------------------------------------------------------
@pytest.mark.parametrize("folder", [
    "Backups #2", "100% safe", "100%25", "plain",
    pytest.param("what?", marks=pytest.mark.skipif(
        os.name == "nt", reason="'?' cannot appear in a Windows folder name")),
])
def test_backup_and_restore_with_special_chars_in_path(services, admin, tmp_path, folder):
    dest = tmp_path / folder
    target = services.backup.create_backup(admin, dest_dir=dest)
    assert target.parent == dest
    assert services.backup.validate_backup(target)["business_name"] == "Test Business"
    services.backup.restore(admin, target)
    assert services.settings.get("business_name") == "Test Business"


def test_v1_database_upgrades_and_keeps_data(services, admin, make_product, sell, methods):
    """A real schema-v1 database (no returns.round_off) is upgraded in place."""
    import sqlite3
    from app.bootstrap import build_services
    from app.database.migrations import read_meta
    pid = make_product(price="100.40", stock="5")
    services.settings.update(admin, {"round_off_total": True})
    res = sell([(pid, 1)])
    path = services.paths.database_file
    services.db.dispose()
    con = sqlite3.connect(path)
    con.execute("ALTER TABLE returns DROP COLUMN round_off")
    con.execute("UPDATE app_meta SET value='1' WHERE key='schema_version'")
    con.commit()
    con.close()

    upgraded = build_services(services.paths)
    try:
        assert read_meta(upgraded.db)["schema_version"] == "2"
        assert any("pre-upgrade-v1" in b["name"] for b in upgraded.backup.list_backups())
        cu = upgraded.auth.login("admin", ADMIN_PASSWORD)
        item = upgraded.sales.get_sale(cu, res["sale_id"])["items"][0]
        ret = _return(upgraded, cu, methods, res["sale_id"], item["id"], 1)
        assert ret["refund_total"] == Decimal("100")
    finally:
        upgraded.db.dispose()


# ---- automatic backups & second copy ------------------------------------------------
def test_automatic_backup_copied_to_second_folder(services, admin, tmp_path):
    usb = tmp_path / "USB #1"
    usb.mkdir()
    services.settings.update(admin, {"backup_copy_folder": str(usb), "backup_keep_count": 2})
    settings = services.settings.get_all()
    assert services.backup.run_automatic(settings) is None
    assert services.backup.run_automatic(settings) is None      # already done today: no-op
    for _ in range(3):
        assert services.backup.run_automatic(settings, on_exit=True) is None
    copies = services.backup.list_backups(usb)
    assert len(copies) == 2                                      # pruned to keep count
    assert services.backup.validate_backup(copies[0]["path"])["business_name"] == "Test Business"
    assert len([b for b in services.backup.list_backups() if b["kind"] == "auto"]) == 2


def test_unavailable_second_folder_warns_but_keeps_local_backup(services, admin, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    services.settings.update(admin, {"backup_copy_folder": str(usb)})
    usb.rmdir()                                                  # drive unplugged
    warning = services.backup.run_automatic(services.settings.get_all(), on_exit=True)
    assert warning and str(usb) in warning
    assert any(b["kind"] == "auto" for b in services.backup.list_backups())
    actions = [r["action"] for r in services.audit.list(admin)[0]]
    assert "BACKUP_COPY_FAILED" in actions
    # a later start the same day (no new backup due) still warns about the missing folder
    warning = services.backup.run_automatic(services.settings.get_all())
    assert warning and "not available" in warning


def test_second_folder_must_exist_when_saved(services, admin, tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        services.settings.update(admin, {"backup_copy_folder": str(tmp_path / "missing")})
    services.settings.update(admin, {"backup_copy_folder": ""})      # clearing is allowed


def test_final_return_never_refunds_below_zero(services, admin, make_product, sell, methods):
    services.settings.update(admin, {"round_off_total": True})
    big = make_product(price="100.10", stock="5")
    tiny = make_product(price="0.30", stock="5")
    res = sell([(big, 1), (tiny, 1)])                      # 100.40 -> paid 100
    items = services.sales.get_sale(admin, res["sale_id"])["items"]
    r1 = _return(services, admin, methods, res["sale_id"], items[0]["id"], 1)
    assert r1["refund_total"] == D("100.10")
    line = [ReturnLineRequest(items[1]["id"], D(1))]
    prev = services.returns.preview(admin, res["sale_id"], line)
    assert prev["refund_total"] == 0 and prev["round_off"] == D("-0.30")
    services.returns.create_return(admin, ReturnRequest(res["sale_id"], line, "edge", []))
    assert services.inventory.verify_ledger() == []


def test_restore_old_version_backup_is_upgraded(services, admin, make_product, sell):
    import sqlite3
    pid = make_product(stock="5")
    sell([(pid, 1)])
    backup = services.backup.create_backup(admin)
    con = sqlite3.connect(backup)                          # turn it into a v1 backup
    con.execute("ALTER TABLE returns DROP COLUMN round_off")
    con.execute("UPDATE app_meta SET value='1' WHERE key='schema_version'")
    con.commit()
    con.close()
    assert services.backup.validate_backup(backup)["schema_version"] == 1
    sell([(pid, 1)])
    services.backup.restore(admin, backup)
    from app.database.migrations import read_meta
    assert read_meta(services.db)["schema_version"] == "2"
    cu = services.auth.login("admin", ADMIN_PASSWORD)
    assert services.sales.list_sales(cu)[1] == 1           # the later sale is gone
    assert stock_of(services, cu, pid) == D("4")            # stock as at the backup
