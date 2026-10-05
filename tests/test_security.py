from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.config.constants import PaymentKind, Perm
from app.models import User
from app.services.errors import AuthenticationError, PermissionDenied, ValidationError
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest
from tests.conftest import ADMIN_PASSWORD

CASHIER_PW = "Cashier-Pass-1"


@pytest.fixture()
def roles(services, admin):
    return {r["name"]: r["id"] for r in services.users.list_roles(admin)}


@pytest.fixture()
def cashier(services, admin, roles):
    services.users.create_user(admin, {"username": "cashier1", "password": CASHIER_PW,
                                       "role_id": roles["Cashier"], "full_name": "Test Cashier"})
    return services.auth.login("cashier1", CASHIER_PW)


def test_password_is_hashed(services, admin):
    with services.db.session() as s:
        u = s.scalar(select(User).where(User.username == "admin"))
        assert ADMIN_PASSWORD not in u.password_hash
        assert u.password_hash.startswith("$2")


def test_login_success_and_failure(services, admin):
    cu = services.auth.login("ADMIN", ADMIN_PASSWORD)  # username case-insensitive
    assert cu.is_admin and Perm.MANAGE_USERS in cu.permissions
    with pytest.raises(AuthenticationError):
        services.auth.login("admin", "wrong-password")
    with pytest.raises(AuthenticationError):
        services.auth.login("nobody", "whatever")


def test_lockout_after_failed_attempts(services, admin):
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            services.auth.login("admin", "bad")
    with pytest.raises(AuthenticationError, match="locked"):
        services.auth.login("admin", ADMIN_PASSWORD)


def test_weak_password_rejected(services, admin, roles):
    with pytest.raises(ValidationError):
        services.users.create_user(admin, {"username": "weak", "password": "short",
                                           "role_id": roles["Cashier"]})
    with pytest.raises(ValidationError):
        services.users.create_user(admin, {"username": "weak", "password": "alllowercase",
                                           "role_id": roles["Cashier"]})


def test_setup_only_once(services, admin):
    with pytest.raises(ValidationError):
        services.auth.complete_setup({"business_name": "X", "admin_username": "other",
                                      "admin_password": ADMIN_PASSWORD,
                                      "admin_password_confirm": ADMIN_PASSWORD})


def test_cashier_cannot_do_admin_things(services, admin, cashier, make_product):
    pid = make_product()
    with pytest.raises(PermissionDenied):
        services.catalog.update_product(cashier, pid, {"name": "x"})
    with pytest.raises(PermissionDenied):
        services.inventory.adjust_stock(cashier, pid, direction="IN", quantity="1", reason="x")
    with pytest.raises(PermissionDenied):
        services.users.list_users(cashier)
    with pytest.raises(PermissionDenied):
        services.settings.update(cashier, {"business_name": "Hacked"})
    with pytest.raises(PermissionDenied):
        services.backup.create_backup(cashier)
    with pytest.raises(PermissionDenied):
        services.audit.list(cashier)
    with pytest.raises(PermissionDenied):
        services.reports.profit_loss(cashier, date.today(), date.today())
    with pytest.raises(PermissionDenied):
        services.expenses.create_expense(cashier, {})


def test_cashier_can_sell_but_not_void(services, admin, cashier, make_product, methods):
    pid = make_product(price="50")
    res = services.sales.create_sale(cashier, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("50"))]))
    with pytest.raises(PermissionDenied):
        services.sales.void_sale(cashier, res["sale_id"], "x")


def test_discount_permission_and_limit(services, admin, cashier, make_product, methods, roles):
    pid = make_product(price="100")
    services.settings.update(admin, {"max_discount_percent": "10"})
    with pytest.raises(PermissionDenied, match="maximum"):
        services.sales.create_sale(cashier, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"), discount_amount=D("20"))],
            payments=[PaymentRequest(methods[PaymentKind.CASH], D("80"))]))
    services.sales.create_sale(cashier, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"), discount_amount=D("10"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("90"))]))
    # admin can override the limit
    services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D("1"), discount_amount=D("20"))],
        payments=[PaymentRequest(methods[PaymentKind.CASH], D("80"))]))
    # remove APPLY_DISCOUNT from cashier role -> any discount fails
    role = next(r for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.save_role(admin, role["id"], "Cashier", "",
                             [p for p in role["permissions"] if p != Perm.APPLY_DISCOUNT])
    cashier2 = services.auth.login("cashier1", CASHIER_PW)
    with pytest.raises(PermissionDenied):
        services.sales.create_sale(cashier2, SaleRequest(
            lines=[SaleLineRequest(pid, D("1"), discount_amount=D("1"))],
            payments=[PaymentRequest(methods[PaymentKind.CASH], D("99"))]))


def test_last_admin_protected(services, admin, roles):
    with pytest.raises(ValidationError):
        services.users.update_user(admin, admin.id, {"is_active": False})
    with pytest.raises(ValidationError):
        services.users.update_user(admin, admin.id, {"role_id": roles["Cashier"]})
    with pytest.raises(ValidationError):
        services.users.delete_role(admin, roles["Administrator"])


def test_deactivated_user_cannot_login(services, admin, cashier):
    services.users.update_user(admin, cashier.id, {"is_active": False})
    with pytest.raises(AuthenticationError):
        services.auth.login("cashier1", CASHIER_PW)


def test_audit_log_records_actions(services, admin, cashier, make_product):
    make_product()
    rows, total = services.audit.list(admin)
    actions = {r["action"] for r in rows}
    assert {"SETUP_COMPLETED", "USER_CREATED", "LOGIN", "PRODUCT_CREATED"} <= actions
    # passwords never appear in audit details
    assert all(CASHIER_PW not in r["details"] and ADMIN_PASSWORD not in r["details"]
               for r in rows)
