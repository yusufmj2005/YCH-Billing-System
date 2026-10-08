"""End-to-end business day: every report, the dashboard and the stock ledger
must agree with each other and with the transactions that were entered."""
from datetime import date
from decimal import Decimal as D

from app.config.constants import PaymentKind
from app.services.purchase_service import PurchaseLineRequest, PurchaseRequest
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest
from tests.conftest import stock_of


def _sale(services, admin, methods, lines, *, split=None, **kw):
    req = SaleRequest(lines=[SaleLineRequest(p, D(str(q)), **extra) for p, q, extra in lines],
                      **kw)
    with services.db.session() as s:
        from app.services.settings_service import get_settings
        total = services.sales.build_cart(s, req, get_settings(s))[2].grand_total
    if split:
        first = D(split)
        req.payments = [PaymentRequest(methods[PaymentKind.CASH], first),
                        PaymentRequest(methods[PaymentKind.UPI], total - first, reference="UPI123")]
    else:
        req.payments = [PaymentRequest(methods[PaymentKind.CASH], total)]
    return services.sales.create_sale(admin, req)


def _ret(services, admin, methods, sale_id, item_idx, qty, restock=True,
         kind=PaymentKind.CASH):
    item = services.sales.get_sale(admin, sale_id)["items"][item_idx]
    line = [ReturnLineRequest(item["id"], D(str(qty)), restock)]
    refund = services.returns.preview(admin, sale_id, line)["refund_total"]
    return services.returns.create_return(admin, ReturnRequest(
        sale_id, line, "reconciliation", [PaymentRequest(methods[kind], refund)]))


def test_business_day_reconciles(services, admin, make_product, methods, taxes):
    today = date.today()
    services.settings.update(admin, {"round_off_total": True})
    yarn = make_product(price="249.50", cost="150", stock="40", tax_id=taxes["Test GST 12"],
                        inclusive=True)
    hook = make_product(price="85.25", cost="40", stock="25", tax_id=taxes["Test GST 5"],
                        inclusive=False)
    kit = make_product(price="1199", cost="700", stock="5")
    opening = {p: stock_of(services, admin, p) for p in (yarn, hook, kit)}

    # --- purchases ------------------------------------------------------------------
    sup = services.partners.save_supplier(admin, None, {"name": "Test Supplier"})
    p1 = services.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=today, lines=[
            PurchaseLineRequest(yarn, D("20"), D("140"), D("50"), D("12")),
            PurchaseLineRequest(hook, D("10"), D("38.5"), D("0"), D("5"))],
        update_cost_prices=False), complete=True)
    p2 = services.purchases.save_draft(admin, None, PurchaseRequest(
        supplier_id=sup, purchase_date=today,
        lines=[PurchaseLineRequest(kit, D("2"), D("690"))], update_cost_prices=False),
        complete=True)
    services.purchases.record_payment(admin, p1["purchase_id"], methods[PaymentKind.CASH],
                                      "1000")
    services.purchases.record_payment(admin, p2["purchase_id"], methods[PaymentKind.UPI],
                                      "1380", reference="NEFT9")
    services.purchases.cancel(admin, p2["purchase_id"], "wrong supplier")

    # --- sales ----------------------------------------------------------------------
    cust = services.partners.save_customer(admin, None, {"name": "Test Customer",
                                                         "phone": "99999 00000"})
    s1 = _sale(services, admin, methods, [(yarn, 3, {}), (hook, 2, {"discount_percent": D(10)})],
               customer_id=cust, split="300")
    s2 = _sale(services, admin, methods, [(kit, 1, {}), (yarn, 1, {"discount_amount": D(20)})],
               bill_discount_amount=D("49.99"))
    s3 = _sale(services, admin, methods, [(hook, 5, {})], tax_mode="INTER")
    s4 = _sale(services, admin, methods, [(yarn, 2, {})])
    services.sales.void_sale(admin, s4["sale_id"], "entered twice")

    # --- returns --------------------------------------------------------------------
    _ret(services, admin, methods, s1["sale_id"], 0, 1)
    _ret(services, admin, methods, s1["sale_id"], 1, 1, restock=False, kind=PaymentKind.UPI)
    _ret(services, admin, methods, s3["sale_id"], 0, 5)            # full return of s3

    # --- expenses & payroll ---------------------------------------------------------
    cats = {c["name"]: c["id"] for c in services.expenses.list_categories()}
    services.expenses.create_expense(admin, {"category_id": cats["Rent"], "amount": "5000",
                                             "expense_date": today,
                                             "payment_method_id": methods[PaymentKind.CASH]})
    e2 = services.expenses.create_expense(admin, {"category_id": cats["Internet"],
                                                  "amount": "799", "expense_date": today})
    services.expenses.void_expense(admin, e2, "duplicate")
    emp = services.staff.save_employee(admin, None, {"employee_code": "E1", "name": "Staff One"})
    pay = services.staff.create_payroll(admin, {"employee_id": emp, "period_start": today,
                                                "period_end": today, "base_salary": "1200"})
    services.staff.mark_payroll_paid(admin, pay, paid_date=today,
                                     payment_method_id=methods[PaymentKind.CASH], reference=None,
                                     record_expense=True)

    # ================================ checks =========================================
    rep = services.reports
    completed = [services.sales.get_sale(admin, x["sale_id"]) for x in (s1, s2, s3)]
    sales_total = sum((x["grand_total"] for x in completed), D(0))
    returns = services.returns.list_returns(admin)[0]
    refunds = sum((r["refund_total"] for r in returns), D(0))
    assert len(returns) == 3

    # stock ledger is consistent and stock levels follow the transactions
    assert services.inventory.verify_ledger() == []
    assert stock_of(services, admin, yarn) == opening[yarn] + 20 - 3 - 1 + 1
    assert stock_of(services, admin, hook) == opening[hook] + 10 - 2 - 5 + 5   # 1 not restocked
    assert stock_of(services, admin, kit) == opening[kit] + 2 - 2 - 1

    # sales: daily summary, register, dashboard, P&L
    daily = rep.sales_summary(admin, today, today).totals
    register = rep.sales_register(admin, today, today).totals
    dash = services.dashboard.overview(admin, today, today)
    with services.db.session() as s:
        pl = rep.profit_loss_figures(s, today, today)
    assert daily["invoices"] == pl["invoice_count"] == 3
    assert daily["total"] == register["total"] == pl["sales_total"] == sales_total
    assert daily["refunds"] == pl["refund_total"] == refunds
    assert daily["net"] == sales_total - refunds
    assert dash["sales_total"] == sales_total and dash["sales_count"] == 3
    assert dash["refunds"] == refunds

    # cash identity: money in minus money back = revenue + GST (both net of returns)
    assert sales_total - refunds == pl["net_sales"] + pl["gst_collected"]

    # tax summary agrees with P&L and with the CGST/SGST/IGST split
    tax = rep.tax_summary(admin, today, today).totals
    assert tax["tax"] == pl["gst_collected"]
    assert tax["cgst"] + tax["sgst"] + tax["igst"] == tax["tax"]
    assert tax["taxable"] == pl["sales_taxable"] - pl["returns_taxable"]

    # product and category reports cover the same goods
    prod = rep.product_sales(admin, today, today).totals
    cat = rep.category_sales(admin, today, today).totals
    assert prod["taxable"] == cat["taxable"] == tax["taxable"]
    assert prod["total"] == cat["total"]

    # payments: receipts = sales, refunds = returns, per-method reports agree
    pm = rep.payment_method_sales(admin, today, today).totals
    ps = rep.payment_summary(admin, today, today).totals
    assert pm["received"] == ps["receipts"] == sales_total
    assert pm["refunded"] == ps["refunds"] == refunds
    assert sum((m["received"] for m in dash["payment_methods"]), D(0)) == sales_total
    assert sum((m["refunded"] for m in dash["payment_methods"]), D(0)) == refunds

    # purchases: cancelled purchase and its voided payment are excluded everywhere
    preg = rep.purchase_register(admin, today, today).totals
    psup = rep.supplier_purchases(admin, today, today).totals
    pprod = rep.product_purchases(admin, today, today).totals
    p1d = services.purchases.get_purchase(admin, p1["purchase_id"])
    assert preg["total"] == psup["total"] == pprod["total"] == pl["purchases_total"] \
        == p1d["grand_total"]
    assert ps["supplier"] == D("1000")
    assert p1d["payment_status"] == "PARTIAL"

    # expenses: void excluded, payroll salary included, all views agree
    ereg = rep.expense_register(admin, today, today).totals
    ecat = rep.expense_by_category(admin, today, today).totals
    assert ereg["amount"] == ecat["amount"] == pl["expenses"] == ps["expenses"] == D("6200")
    assert dash["expenses"] == D("6200")

    # P&L arithmetic
    assert pl["gross_profit"] == pl["net_sales"] - pl["cogs"]
    assert pl["net_profit"] == pl["gross_profit"] - pl["expenses"]

    # inventory valuation equals stock x cost
    val = rep.inventory_valuation(admin).totals
    expected = sum((stock_of(services, admin, p) * services.catalog.get_product(admin, p)
                    ["purchase_price"] for p in (yarn, hook, kit)), D(0))
    assert val["value"] == expected == dash["inventory_value"]
