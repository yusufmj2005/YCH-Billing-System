"""Business rules of the supporting modules: payment methods, partners,
expenses, staff, roles and purchases."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.config.constants import PaymentKind, Perm
from app.services.errors import InsufficientStock, PermissionDenied, ValidationError
from app.services.purchase_service import PurchaseLineRequest, PurchaseRequest
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest

TODAY = date.today()


# ---- payment methods ---------------------------------------------------------------
def test_custom_payment_method_and_rules(services, admin, make_product, methods):
    mid = services.payment_methods.save(admin, None, {"name": "Store Credit",
                                                      "requires_description": True})
    with pytest.raises(ValidationError, match="already exists"):
        services.payment_methods.save(admin, None, {"name": "store credit"})
    pid = make_product(price="50")
    with pytest.raises(ValidationError, match="describe"):
        services.sales.create_sale(admin, SaleRequest(
            [SaleLineRequest(pid, D(1))], [PaymentRequest(mid, D("50"))]))
    services.sales.create_sale(admin, SaleRequest(
        [SaleLineRequest(pid, D(1))], [PaymentRequest(mid, D("50"), description="Voucher 7")]))


def test_cannot_disable_every_payment_method(services, admin):
    active = services.payment_methods.list()
    for m in active[:-1]:
        services.payment_methods.save(admin, m["id"], {"name": m["name"], "is_active": False})
    last = active[-1]
    with pytest.raises(ValidationError, match="At least one"):
        services.payment_methods.save(admin, last["id"], {"name": last["name"],
                                                          "is_active": False})


@pytest.mark.parametrize("ref", ["4111 1111 1111 1111", "5500-0000-0000-0004",
                                 "378282246310005"])
def test_card_numbers_never_stored_as_reference(services, admin, make_product, methods, ref):
    pid = make_product(price="10")
    with pytest.raises(ValidationError, match="card number"):
        services.sales.create_sale(admin, SaleRequest(
            [SaleLineRequest(pid, D(1))],
            [PaymentRequest(methods[PaymentKind.DEBIT_CARD], D("10"), reference=ref)]))


def test_payment_total_must_match_invoice(services, admin, make_product, methods):
    pid = make_product(price="100", stock="5")
    for paid in ("99.99", "100.01"):
        with pytest.raises(ValidationError, match="does not match"):
            services.sales.create_sale(admin, SaleRequest(
                [SaleLineRequest(pid, D(1))], [PaymentRequest(methods[PaymentKind.CASH], D(paid))]))
    assert services.sales.list_sales(admin)[1] == 0      # nothing half-saved


# ---- customers & suppliers ---------------------------------------------------------
@pytest.mark.parametrize("field, value", [("phone", "abc"), ("email", "x@"),
                                          ("gstin", "22AAAAA0000A1Y5"), ("name", "")])
def test_contact_validation(services, admin, field, value):
    data = {"name": "Valid Name", field: value}
    with pytest.raises(ValidationError):
        services.partners.save_customer(admin, None, data)
    with pytest.raises(ValidationError):
        services.partners.save_supplier(admin, None, data)


def test_customer_history_is_net_of_refunds_and_voids(services, admin, make_product, methods):
    cid = services.partners.save_customer(admin, None, {"name": "Regular", "phone": "12345"})
    pid = make_product(price="100", stock="10")

    def sale(qty):
        return services.sales.create_sale(admin, SaleRequest(
            [SaleLineRequest(pid, D(qty))],
            [PaymentRequest(methods[PaymentKind.CASH], D(100 * qty))], customer_id=cid))
    s1, s2 = sale(2), sale(1)
    services.sales.void_sale(admin, s2["sale_id"], "mistake")
    item = services.sales.get_sale(admin, s1["sale_id"])["items"][0]
    services.returns.create_return(admin, ReturnRequest(
        s1["sale_id"], [ReturnLineRequest(item["id"], D(1))], "faulty",
        [PaymentRequest(methods[PaymentKind.CASH], D("100"))]))
    h = services.partners.customer_history(admin, cid)
    assert h["invoice_count"] == 1
    assert h["total_spent"] == D("100")
    assert services.partners.list_customers(admin, search="Regu")[0]["id"] == cid


def test_cashier_cannot_edit_suppliers(services, admin):
    cashier_role = next(r["id"] for r in services.users.list_roles(admin)
                        if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "cashier", "password": "Cashier-123",
                                       "role_id": cashier_role, "must_change_password": False})
    cu = services.auth.login("cashier", "Cashier-123")
    with pytest.raises(PermissionDenied):
        services.partners.save_supplier(cu, None, {"name": "X"})
    with pytest.raises(PermissionDenied):
        services.partners.list_suppliers(cu)


# ---- expenses ----------------------------------------------------------------------
def _cat(services, name="Rent"):
    return next(c["id"] for c in services.expenses.list_categories() if c["name"] == name)


def test_expense_rules(services, admin):
    with pytest.raises(ValidationError, match="future"):
        services.expenses.create_expense(admin, {"category_id": _cat(services), "amount": "10",
                                                 "expense_date": TODAY + timedelta(days=1)})
    with pytest.raises(ValidationError):
        services.expenses.create_expense(admin, {"category_id": _cat(services), "amount": "0",
                                                 "expense_date": TODAY})
    eid = services.expenses.create_expense(admin, {"category_id": _cat(services),
                                                   "amount": "10", "expense_date": TODAY})
    with pytest.raises(ValidationError, match="Reason"):
        services.expenses.void_expense(admin, eid, "")
    services.expenses.void_expense(admin, eid, "typo")
    with pytest.raises(ValidationError, match="already void"):
        services.expenses.void_expense(admin, eid, "again")
    rows, total, amount = services.expenses.list_expenses(admin, include_void=True)
    assert total == 1 and amount == 0


# ---- staff -------------------------------------------------------------------------
def test_payroll_rules(services, admin, methods):
    emp = services.staff.save_employee(admin, None, {"employee_code": "E1", "name": "A"})
    with pytest.raises(ValidationError, match="already has this Employee ID"):
        services.staff.save_employee(admin, None, {"employee_code": "E1", "name": "B"})
    start = TODAY.replace(day=1)
    pay = services.staff.create_payroll(admin, {"employee_id": emp, "period_start": start,
                                                "period_end": TODAY, "base_salary": "15000",
                                                "allowances": "500", "deductions": "250"})
    with pytest.raises(ValidationError, match="already exists"):
        services.staff.create_payroll(admin, {"employee_id": emp, "period_start": TODAY,
                                              "period_end": TODAY, "base_salary": "1"})
    with pytest.raises(ValidationError, match="Deductions"):
        services.staff.create_payroll(admin, {"employee_id": emp, "period_start": start,
                                              "period_end": start, "base_salary": "10",
                                              "deductions": "11"})
    services.staff.mark_payroll_paid(admin, pay, paid_date=TODAY,
                                     payment_method_id=methods[PaymentKind.BANK_TRANSFER],
                                     reference="SAL-1", record_expense=True)
    rows, _, amount = services.expenses.list_expenses(admin)
    assert amount == D("15250") and rows[0]["from_payroll"]
    with pytest.raises(ValidationError, match="payroll"):
        services.expenses.void_expense(admin, rows[0]["id"], "x")
    with pytest.raises(ValidationError, match="unpaid"):
        services.staff.mark_payroll_paid(admin, pay, paid_date=TODAY, payment_method_id=None,
                                         reference=None, record_expense=False)
    services.staff.cancel_payroll(admin, pay)
    assert services.expenses.list_expenses(admin)[2] == 0     # salary expense voided too


def test_attendance_and_leave_rules(services, admin):
    emp = services.staff.save_employee(admin, None, {"employee_code": "E2", "name": "B"})
    with pytest.raises(ValidationError, match="future"):
        services.staff.save_attendance(admin, emp, TODAY + timedelta(days=1),
                                       {"status": "Present"})
    with pytest.raises(ValidationError, match="after check-in"):
        services.staff.save_attendance(admin, emp, TODAY, {"status": "Present",
                                                           "check_in": "18:00",
                                                           "check_out": "09:00"})
    with pytest.raises(ValidationError, match="HH:MM"):
        services.staff.save_attendance(admin, emp, TODAY, {"status": "Present",
                                                           "check_in": "9am"})
    services.staff.save_attendance(admin, emp, TODAY, {"status": "Present", "check_in": "09:00"})
    services.staff.save_attendance(admin, emp, TODAY, {"status": "Half Day"})  # updates
    hist = services.staff.attendance_history(admin, emp, TODAY, TODAY)
    assert len(hist) == 1 and hist[0]["status"] == "Half Day"

    lt = services.staff.save_leave_type(admin, None, {"name": "Casual leave"})
    lid = services.staff.create_leave(admin, {"employee_id": emp, "leave_type_id": lt,
                                              "start_date": TODAY, "end_date": TODAY})
    with pytest.raises(ValidationError, match="already has leave"):
        services.staff.create_leave(admin, {"employee_id": emp, "leave_type_id": lt,
                                            "start_date": TODAY, "end_date": TODAY})
    services.staff.decide_leave(admin, lid, approve=False)
    with pytest.raises(ValidationError, match="pending"):
        services.staff.decide_leave(admin, lid, approve=True)
    # rejected leave no longer blocks a new request for the same dates
    services.staff.create_leave(admin, {"employee_id": emp, "leave_type_id": lt,
                                        "start_date": TODAY, "end_date": TODAY})


# ---- roles & administrators --------------------------------------------------------
def test_role_and_admin_safeguards(services, admin):
    roles = {r["name"]: r for r in services.users.list_roles(admin)}
    admin_role = roles["Administrator"]["id"]
    with pytest.raises(ValidationError, match="cannot be renamed"):
        services.users.save_role(admin, admin_role, "Boss", "", [])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        services.users.delete_role(admin, admin_role)
    with pytest.raises(ValidationError, match="own account"):
        services.users.update_user(admin, admin.id, {"is_active": False})
    with pytest.raises(ValidationError, match="At least one active administrator"):
        services.users.update_user(admin, admin.id, {"role_id": roles["Manager"]["id"]})
    rid = services.users.save_role(admin, None, "Helper", "", [Perm.VIEW_PRODUCTS])
    services.users.create_user(admin, {"username": "helper", "password": "Helper-123",
                                       "role_id": rid})
    with pytest.raises(ValidationError, match="assigned to users"):
        services.users.delete_role(admin, rid)


def test_permission_change_takes_effect_on_reload(services, admin):
    rid = services.users.save_role(admin, None, "Counter", "", [Perm.VIEW_PRODUCTS])
    services.users.create_user(admin, {"username": "counter", "password": "Counter-123",
                                       "role_id": rid, "must_change_password": False})
    cu = services.auth.login("counter", "Counter-123")
    assert not cu.has(Perm.CREATE_SALE)
    services.users.save_role(admin, rid, "Counter", "", [Perm.VIEW_PRODUCTS, Perm.CREATE_SALE])
    assert services.auth.reload(cu).has(Perm.CREATE_SALE)


# ---- purchases ---------------------------------------------------------------------
def test_purchase_lifecycle_rules(services, admin, make_product, methods, sell):
    pid = make_product(stock="0", cost="10")
    sup = services.partners.save_supplier(admin, None, {"name": "Supplier"})
    req = PurchaseRequest(supplier_id=sup, purchase_date=TODAY,
                          lines=[PurchaseLineRequest(pid, D("10"), D("12"))])
    draft = services.purchases.save_draft(admin, None, req)
    with pytest.raises(ValidationError, match="completed purchases"):
        services.purchases.record_payment(admin, draft["purchase_id"],
                                          methods[PaymentKind.CASH], "1")
    services.purchases.complete(admin, draft["purchase_id"])
    with pytest.raises(ValidationError, match="Only draft"):
        services.purchases.save_draft(admin, draft["purchase_id"], req)
    with pytest.raises(ValidationError, match="balance"):
        services.purchases.record_payment(admin, draft["purchase_id"],
                                          methods[PaymentKind.CASH], "120.01")
    services.purchases.record_payment(admin, draft["purchase_id"],
                                      methods[PaymentKind.CASH], "120")
    assert services.purchases.get_purchase(admin, draft["purchase_id"])["payment_status"] \
        == "PAID"
    assert services.catalog.get_product(admin, pid)["purchase_price"] == D("12")
    sell([(pid, 5)])
    # goods already sold: cancelling would make stock negative
    with pytest.raises(InsufficientStock):
        services.purchases.cancel(admin, draft["purchase_id"], "returned to supplier")
    assert services.inventory.verify_ledger() == []
