"""Edge cases and regression tests found during exploratory testing."""
from decimal import Decimal

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


@pytest.mark.xfail(strict=True, reason="Known bug: refunds ignore invoice round-off, so a "
                                       "rounded-down sale refunds more than was paid")
def test_full_return_never_refunds_more_than_paid(services, admin, make_product, sell):
    services.settings.update(admin, {"round_off_total": True})
    pid = make_product(price="100.40", stock="5")
    res = sell([(pid, 1)])
    assert res["grand_total"] == Decimal("100")
    item = services.sales.get_sale(admin, res["sale_id"])["items"][0]
    refund = services.returns.preview(
        admin, res["sale_id"], [ReturnLineRequest(item["id"], Decimal(1))])["refund_total"]
    assert refund <= res["grand_total"]


# ---- settings --------------------------------------------------------------------
def test_invoice_prefix_wildcard_chars_are_literal(services, admin, make_product, sell):
    pid = make_product()
    services.settings.update(admin, {"invoice_prefix": "AB"})
    sell([(pid, 1)])
    # "A_" is a different prefix; "_" must not act as a LIKE wildcard matching "AB…".
    services.settings.update(admin, {"invoice_prefix": "A_", "next_invoice_number": 1})


# ---- backup ----------------------------------------------------------------------
@pytest.mark.parametrize("folder", ["Backups #2", "what?", "100% safe", "100%25", "plain"])
def test_backup_and_restore_with_special_chars_in_path(services, admin, tmp_path, folder):
    dest = tmp_path / folder
    target = services.backup.create_backup(admin, dest_dir=dest)
    assert target.parent == dest
    assert services.backup.validate_backup(target)["business_name"] == "Test Business"
    services.backup.restore(admin, target)
    assert services.settings.get("business_name") == "Test Business"
