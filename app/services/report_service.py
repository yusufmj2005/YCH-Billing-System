"""Reports. Every number is aggregated from stored transactions.

Date basis
    Sales / payments / returns: transaction timestamp (local time).
    Purchases: purchase date. Expenses: expense date.
Voided sales and cancelled purchases are excluded; void expenses excluded.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select

from app.config.constants import (MOVEMENT_TYPE_LABELS, PaymentDirection, Perm, PurchaseStatus,
                                  SaleStatus)
from app.database.database import Database
from app.models import (Category, Expense, ExpenseCategory, InventoryMovement, Payment,
                        PaymentMethod, Product, Purchase, PurchaseItem, ReturnItem, Sale,
                        SaleItem, SaleReturn, Supplier)
from app.reports.base import Col, ReportResult
from app.security.auth import CurrentUser, require
from app.services.errors import ValidationError
from app.services.inventory_service import low_stock_condition
from app.services.settings_service import get_settings
from app.utils.dates import day_end_exclusive, day_start, fmt_date
from app.utils.money import ZERO, money

PROFIT_LOSS_METHOD = [
    "Net sales = taxable value of completed sales (excluding GST) minus taxable value of "
    "returns, plus invoice round-off adjustments (net of round-off given back when an "
    "invoice is fully returned).",
    "Cost of goods sold (COGS) = cost price recorded on each sale line at the time of sale, "
    "minus the cost of returned items that were put back into stock.",
    "Gross profit = Net sales - COGS.",
    "Operating expenses = recorded, non-void expenses dated within the period "
    "(including salary expenses recorded from payroll).",
    "Net profit / loss = Gross profit - Operating expenses.",
    "Purchases are shown for information only: inventory purchases become cost when the goods "
    "are sold (through COGS), so they are not subtracted again.",
    "GST collected is a liability and is not counted as revenue.",
    "These figures support business accounting; they are not statutory financial statements.",
]


def _rng(date_from: date, date_to: date):
    if date_to < date_from:
        raise ValidationError("The end date must be on or after the start date.")
    return day_start(date_from), day_end_exclusive(date_to)


def _period_key(d: date, period: str) -> tuple[str, date]:
    if period == "week":
        start = d - timedelta(days=d.weekday())
        return f"Week of {fmt_date(start)}", start
    if period == "month":
        start = d.replace(day=1)
        return start.strftime("%B %Y"), start
    return fmt_date(d), d


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class ReportService:
    def __init__(self, db: Database):
        self.db = db

    # =========================== SALES ==========================================
    def sales_summary(self, actor: CurrentUser, date_from: date, date_to: date,
                      period: str = "day") -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            day = func.date(Sale.created_at)
            sales = s.execute(
                select(day, func.count(Sale.id), func.sum(Sale.gross_total),
                       func.sum(Sale.item_discount_total), func.sum(Sale.bill_discount),
                       func.sum(Sale.taxable_total), func.sum(Sale.tax_total),
                       func.sum(Sale.grand_total))
                .where(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= start,
                       Sale.created_at < end).group_by(day)).all()
            rday = func.date(SaleReturn.created_at)
            refunds = dict(s.execute(
                select(rday, func.sum(SaleReturn.refund_total))
                .where(SaleReturn.created_at >= start, SaleReturn.created_at < end)
                .group_by(rday)).all())
        buckets: "OrderedDict[date, dict]" = OrderedDict()
        keys = set()
        for d_str, *_ in sales:
            keys.add(_as_date(d_str))
        keys |= {_as_date(k) for k in refunds}
        for d in sorted(keys):
            label, k = _period_key(d, period)
            buckets.setdefault(k, {"period": label, "invoices": 0, "gross": ZERO,
                                   "discount": ZERO, "taxable": ZERO, "tax": ZERO,
                                   "total": ZERO, "refunds": ZERO, "net": ZERO})
        for d_str, cnt, gross, idisc, bdisc, taxable, tax, total in sales:
            _, k = _period_key(_as_date(d_str), period)
            b = buckets[k]
            b["invoices"] += cnt
            b["gross"] += gross or ZERO
            b["discount"] += (idisc or ZERO) + (bdisc or ZERO)
            b["taxable"] += taxable or ZERO
            b["tax"] += tax or ZERO
            b["total"] += total or ZERO
        for d_str, ref in refunds.items():
            _, k = _period_key(_as_date(d_str), period)
            buckets[k]["refunds"] += ref or ZERO
        rows = list(buckets.values())
        for r in rows:
            r["net"] = r["total"] - r["refunds"]
        totals = {"period": "Total"}
        for key in ("invoices", "gross", "discount", "taxable", "tax", "total", "refunds", "net"):
            totals[key] = sum((r[key] for r in rows), 0 if key == "invoices" else ZERO)
        title = {"day": "Daily Sales", "week": "Weekly Sales", "month": "Monthly Sales"}[period]
        return ReportResult(title, [
            Col("period", "Period"), Col("invoices", "Invoices", "int"),
            Col("gross", "Gross", "money"), Col("discount", "Discounts", "money"),
            Col("taxable", "Taxable value", "money"), Col("tax", "Tax", "money"),
            Col("total", "Sales total", "money"), Col("refunds", "Refunds", "money"),
            Col("net", "Net sales", "money")], rows, totals,
            notes=["Voided sales are excluded. Refunds are counted on the date of the return."])

    def sales_register(self, actor: CurrentUser, date_from: date, date_to: date,
                       customer_id: int | None = None,
                       payment_method_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            q = select(Sale).where(Sale.created_at >= start, Sale.created_at < end)
            if customer_id:
                q = q.where(Sale.customer_id == customer_id)
            if payment_method_id:
                q = q.where(Sale.id.in_(select(Payment.sale_id).where(
                    Payment.payment_method_id == payment_method_id,
                    Payment.direction == PaymentDirection.IN)))
            rows = []
            for x in s.scalars(q.order_by(Sale.created_at)):
                rows.append({
                    "invoice_no": x.invoice_no, "created_at": x.created_at,
                    "customer": x.customer_name or "Walk-in", "status": x.status,
                    "taxable": x.taxable_total, "cgst": x.cgst_total, "sgst": x.sgst_total,
                    "igst": x.igst_total, "total": x.grand_total,
                    "payments": ", ".join(f"{p.method_name} {money(p.amount)}"
                                          for p in x.payments
                                          if p.direction == PaymentDirection.IN),
                })
        done = [r for r in rows if r["status"] == SaleStatus.COMPLETED]
        totals = {"invoice_no": "Total (completed)"}
        for k in ("taxable", "cgst", "sgst", "igst", "total"):
            totals[k] = sum((r[k] for r in done), ZERO)
        return ReportResult("Sales Register", [
            Col("invoice_no", "Invoice"), Col("created_at", "Date", "datetime"),
            Col("customer", "Customer"), Col("status", "Status"),
            Col("taxable", "Taxable", "money"), Col("cgst", "CGST", "money"),
            Col("sgst", "SGST", "money"), Col("igst", "IGST", "money"),
            Col("total", "Total", "money"), Col("payments", "Payments")], rows, totals)

    def product_sales(self, actor: CurrentUser, date_from: date, date_to: date,
                      category_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        show_cost = actor.has(Perm.VIEW_FINANCIAL_REPORTS)
        with self.db.session() as s:
            q = (select(SaleItem.product_id, func.max(SaleItem.product_name),
                        func.sum(SaleItem.quantity), func.sum(SaleItem.taxable_amount),
                        func.sum(SaleItem.tax_amount), func.sum(SaleItem.line_total),
                        func.sum(SaleItem.cost_total))
                 .join(Sale).where(Sale.status == SaleStatus.COMPLETED,
                                   Sale.created_at >= start, Sale.created_at < end)
                 .group_by(SaleItem.product_id))
            rq = (select(ReturnItem.product_id, func.sum(ReturnItem.quantity),
                         func.sum(ReturnItem.taxable_amount), func.sum(ReturnItem.refund_amount),
                         func.sum(ReturnItem.cost_total))
                  .join(SaleReturn).where(SaleReturn.created_at >= start,
                                          SaleReturn.created_at < end)
                  .group_by(ReturnItem.product_id))
            if category_id:
                ids = select(Product.id).where(Product.category_id == category_id)
                q = q.where(SaleItem.product_id.in_(ids))
                rq = rq.where(ReturnItem.product_id.in_(ids))
            sold = s.execute(q).all()
            returned = {r[0]: r[1:] for r in s.execute(rq).all()}
            cats = dict(s.execute(select(Product.id, Category.name).join(
                Category, Product.category_id == Category.id, isouter=True)).all())
            rows = []
            for pid, name, qty, taxable, tax, total, cost in sold:
                rq_, rtax, rref, rcost = returned.pop(pid, (ZERO, ZERO, ZERO, ZERO))
                net_taxable = (taxable or ZERO) - (rtax or ZERO)
                net_cost = (cost or ZERO) - (rcost or ZERO)
                row = {"product": name, "category": cats.get(pid) or "",
                       "qty": qty or ZERO, "returned": rq_ or ZERO,
                       "net_qty": (qty or ZERO) - (rq_ or ZERO),
                       "taxable": net_taxable, "total": (total or ZERO) - (rref or ZERO)}
                if show_cost:
                    row["cost"] = net_cost
                    row["margin"] = net_taxable - net_cost
                rows.append(row)
            for pid, (rq_, rtax, rref, rcost) in returned.items():
                name = s.scalar(select(Product.name).where(Product.id == pid))
                row = {"product": name, "category": cats.get(pid) or "", "qty": ZERO,
                       "returned": rq_, "net_qty": -rq_, "taxable": -rtax, "total": -rref}
                if show_cost:
                    row["cost"] = -(rcost or ZERO)
                    row["margin"] = -rtax + (rcost or ZERO)
                rows.append(row)
        rows.sort(key=lambda r: r["total"], reverse=True)
        cols = [Col("product", "Product"), Col("category", "Category"),
                Col("qty", "Qty sold", "qty"), Col("returned", "Qty returned", "qty"),
                Col("net_qty", "Net qty", "qty"), Col("taxable", "Net taxable", "money"),
                Col("total", "Net total", "money")]
        if show_cost:
            cols += [Col("cost", "Cost", "money"), Col("margin", "Gross margin", "money")]
        totals = {"product": "Total"}
        for c in cols[2:]:
            totals[c.key] = sum((r.get(c.key, ZERO) for r in rows), ZERO)
        return ReportResult("Product-wise Sales", cols, rows, totals,
                            notes=["Net values deduct returns made in the same period. "
                                   "Margin uses the cost price recorded at the time of sale."])

    def category_sales(self, actor: CurrentUser, date_from: date, date_to: date) -> ReportResult:
        base = self.product_sales(actor, date_from, date_to)
        groups: "OrderedDict[str, dict]" = OrderedDict()
        for r in base.rows:
            g = groups.setdefault(r["category"] or "Uncategorised",
                                  {"category": r["category"] or "Uncategorised",
                                   "net_qty": ZERO, "taxable": ZERO, "total": ZERO})
            g["net_qty"] += r["net_qty"]
            g["taxable"] += r["taxable"]
            g["total"] += r["total"]
        rows = sorted(groups.values(), key=lambda r: r["total"], reverse=True)
        totals = {"category": "Total", "net_qty": sum((r["net_qty"] for r in rows), ZERO),
                  "taxable": sum((r["taxable"] for r in rows), ZERO),
                  "total": sum((r["total"] for r in rows), ZERO)}
        return ReportResult("Category-wise Sales", [
            Col("category", "Category"), Col("net_qty", "Net qty", "qty"),
            Col("taxable", "Net taxable", "money"), Col("total", "Net total", "money")],
            rows, totals)

    def payment_method_sales(self, actor: CurrentUser, date_from: date,
                             date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            base = and_(Payment.is_void.is_(False), Payment.created_at >= start,
                        Payment.created_at < end)
            recv = s.execute(select(Payment.method_name, func.count(Payment.id),
                                    func.sum(Payment.amount))
                             .where(base, Payment.direction == PaymentDirection.IN,
                                    Payment.sale_id.isnot(None))
                             .group_by(Payment.method_name)).all()
            refs = dict(s.execute(select(Payment.method_name, func.sum(Payment.amount))
                                  .where(base, Payment.return_id.isnot(None))
                                  .group_by(Payment.method_name)).all())
        rows = {}
        for name, cnt, amt in recv:
            rows[name] = {"method": name, "count": cnt, "received": amt or ZERO,
                          "refunded": ZERO}
        for name, amt in refs.items():
            rows.setdefault(name, {"method": name, "count": 0, "received": ZERO,
                                   "refunded": ZERO})["refunded"] = amt or ZERO
        out = sorted(rows.values(), key=lambda r: r["received"], reverse=True)
        for r in out:
            r["net"] = r["received"] - r["refunded"]
        totals = {"method": "Total", "count": sum(r["count"] for r in out),
                  "received": sum((r["received"] for r in out), ZERO),
                  "refunded": sum((r["refunded"] for r in out), ZERO),
                  "net": sum((r["net"] for r in out), ZERO)}
        return ReportResult("Payment-method Sales", [
            Col("method", "Payment method"), Col("count", "Payments", "int"),
            Col("received", "Recorded receipts", "money"),
            Col("refunded", "Recorded refunds", "money"), Col("net", "Net recorded", "money")],
            out, totals, notes=["Amounts are recorded payments, not bank or account balances."])

    def tax_summary(self, actor: CurrentUser, date_from: date, date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            sold = s.execute(
                select(SaleItem.tax_rate, func.sum(SaleItem.taxable_amount),
                       func.sum(SaleItem.cgst_amount), func.sum(SaleItem.sgst_amount),
                       func.sum(SaleItem.igst_amount), func.sum(SaleItem.tax_amount))
                .join(Sale).where(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= start,
                                  Sale.created_at < end).group_by(SaleItem.tax_rate)).all()
            ret = s.execute(
                select(SaleItem.tax_rate, func.sum(ReturnItem.taxable_amount),
                       func.sum(ReturnItem.cgst_amount), func.sum(ReturnItem.sgst_amount),
                       func.sum(ReturnItem.igst_amount), func.sum(ReturnItem.tax_amount))
                .select_from(ReturnItem).join(SaleItem, ReturnItem.sale_item_id == SaleItem.id)
                .join(SaleReturn, ReturnItem.return_id == SaleReturn.id)
                .where(SaleReturn.created_at >= start, SaleReturn.created_at < end)
                .group_by(SaleItem.tax_rate)).all()
        rows: dict = {}
        for sign, data in ((1, sold), (-1, ret)):
            for rate, *vals in data:
                r = rows.setdefault(rate, {"rate": rate, "taxable": ZERO, "cgst": ZERO,
                                           "sgst": ZERO, "igst": ZERO, "tax": ZERO})
                for k, val in zip(("taxable", "cgst", "sgst", "igst", "tax"), vals):
                    r[k] += sign * (val or ZERO)
        out = [rows[k] for k in sorted(rows)]
        totals = {"rate": None}
        for k in ("taxable", "cgst", "sgst", "igst", "tax"):
            totals[k] = sum((r[k] for r in out), ZERO)
        return ReportResult("Tax Summary (Sales)", [
            Col("rate", "Tax rate", "pct"), Col("taxable", "Taxable value", "money"),
            Col("cgst", "CGST", "money"), Col("sgst", "SGST", "money"),
            Col("igst", "IGST", "money"), Col("tax", "Total tax", "money")], out, totals,
            notes=["Net of returns in the period. Rates are those configured by the business "
                   "and recorded on each invoice line. This summary is not a tax filing."])

    # =========================== GSTR-1 =========================================
    def gstr1(self, actor: CurrentUser, section: str, date_from: date,
              date_to: date) -> ReportResult:
        """GSTR-1 working reports: b2b, b2c, cdnr, hsn or docs."""
        from app.services import gst_returns as g
        require(actor, Perm.VIEW_REPORTS)
        fn = {"b2b": g.b2b, "b2c": g.b2c, "cdnr": g.credit_notes_b2b, "hsn": g.hsn_summary,
              "docs": g.documents_issued}.get(section)
        if fn is None:
            raise ValidationError("Unknown GSTR-1 section.")
        with self.db.session() as s:
            return fn(s, date_from, date_to)

    # =========================== INVENTORY ======================================
    def _threshold(self, s) -> Decimal:
        return Decimal(str(get_settings(s).get("low_stock_threshold") or "0"))

    def current_stock(self, actor: CurrentUser, category_id: int | None = None,
                      low_only: bool = False) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        with self.db.session() as s:
            threshold = self._threshold(s)
            q = select(Product).where(Product.is_active.is_(True))
            if category_id:
                q = q.where(Product.category_id == category_id)
            if low_only:
                q = q.where(low_stock_condition(threshold))
            rows = []
            for p in s.scalars(q.order_by(Product.name)):
                level = p.min_stock_level if p.min_stock_level is not None else threshold
                rows.append({"product": p.name, "sku": p.sku or "",
                             "category": p.category.name if p.category else "",
                             "unit": p.unit, "stock": p.current_stock, "min": level,
                             "status": "LOW" if p.current_stock <= level else "OK"})
        title = "Low-stock Items" if low_only else "Current Stock"
        return ReportResult(title, [
            Col("product", "Product"), Col("sku", "SKU"), Col("category", "Category"),
            Col("unit", "Unit"), Col("stock", "In stock", "qty"),
            Col("min", "Minimum level", "qty"), Col("status", "Status")], rows,
            notes=[f"Products without their own minimum level use the global threshold "
                   f"({threshold})."])

    def inventory_valuation(self, actor: CurrentUser,
                            category_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        with self.db.session() as s:
            q = select(Product).where(Product.is_active.is_(True))
            if category_id:
                q = q.where(Product.category_id == category_id)
            rows = []
            for p in s.scalars(q.order_by(Product.name)):
                stock = p.current_stock
                rows.append({"product": p.name, "category": p.category.name if p.category else "",
                             "stock": stock, "cost": p.purchase_price,
                             "value": money(max(stock, ZERO) * p.purchase_price),
                             "price": p.selling_price,
                             "retail": money(max(stock, ZERO) * p.selling_price)})
        totals = {"product": "Total", "value": sum((r["value"] for r in rows), ZERO),
                  "retail": sum((r["retail"] for r in rows), ZERO)}
        return ReportResult("Inventory Valuation", [
            Col("product", "Product"), Col("category", "Category"), Col("stock", "In stock", "qty"),
            Col("cost", "Cost price", "money"), Col("value", "Value at cost", "money"),
            Col("price", "Selling price", "money"), Col("retail", "Value at selling price", "money")],
            rows, totals, notes=["Valued at each product's current cost price "
                                 "(last purchase cost when purchases update cost prices). "
                                 "Negative stock is valued at zero."])

    def stock_movement(self, actor: CurrentUser, date_from: date, date_to: date,
                       product_id: int | None = None,
                       movement_type: str | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            q = select(InventoryMovement).where(InventoryMovement.created_at >= start,
                                                InventoryMovement.created_at < end)
            if product_id:
                q = q.where(InventoryMovement.product_id == product_id)
            if movement_type:
                q = q.where(InventoryMovement.movement_type == movement_type)
            rows = [{"created_at": m.created_at, "product": m.product.name,
                     "type": MOVEMENT_TYPE_LABELS.get(m.movement_type, m.movement_type),
                     "qty": m.quantity, "balance": m.balance_after,
                     "reference": m.reference_no or "", "reason": m.reason or "",
                     "user": m.user.username if m.user else ""}
                    for m in s.scalars(q.order_by(InventoryMovement.id).limit(20000))]
        return ReportResult("Stock Movement", [
            Col("created_at", "Date", "datetime"), Col("product", "Product"),
            Col("type", "Movement"), Col("qty", "Quantity", "qty"),
            Col("balance", "Balance after", "qty"), Col("reference", "Reference"),
            Col("reason", "Reason"), Col("user", "User")], rows)

    # =========================== PURCHASES ======================================
    def _purchase_q(self, date_from, date_to, supplier_id):
        if date_to < date_from:
            raise ValidationError("The end date must be on or after the start date.")
        q = select(Purchase).where(Purchase.status == PurchaseStatus.COMPLETED,
                                   Purchase.purchase_date >= date_from,
                                   Purchase.purchase_date <= date_to)
        if supplier_id:
            q = q.where(Purchase.supplier_id == supplier_id)
        return q

    def purchase_register(self, actor: CurrentUser, date_from: date, date_to: date,
                          supplier_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        with self.db.session() as s:
            rows = [{"purchase_no": p.purchase_no, "date": p.purchase_date,
                     "supplier": p.supplier.name, "ref": p.supplier_invoice_no or "",
                     "subtotal": p.subtotal, "discount": p.discount_total, "tax": p.tax_total,
                     "total": p.grand_total, "paid": p.amount_paid,
                     "due": p.grand_total - p.amount_paid, "status": p.payment_status}
                    for p in s.scalars(self._purchase_q(date_from, date_to, supplier_id)
                                       .order_by(Purchase.purchase_date, Purchase.id))]
        totals = {"purchase_no": "Total"}
        for k in ("subtotal", "discount", "tax", "total", "paid", "due"):
            totals[k] = sum((r[k] for r in rows), ZERO)
        return ReportResult("Purchase Register", [
            Col("purchase_no", "Purchase #"), Col("date", "Date", "date"),
            Col("supplier", "Supplier"), Col("ref", "Supplier invoice"),
            Col("subtotal", "Gross", "money"), Col("discount", "Discount", "money"),
            Col("tax", "Tax", "money"), Col("total", "Total", "money"),
            Col("paid", "Paid", "money"), Col("due", "Due", "money"),
            Col("status", "Payment status")], rows, totals,
            notes=["Completed purchases only (drafts and cancelled purchases excluded)."])

    def supplier_purchases(self, actor: CurrentUser, date_from: date,
                           date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        with self.db.session() as s:
            sub = self._purchase_q(date_from, date_to, None).subquery()
            data = s.execute(
                select(Supplier.name, func.count(sub.c.id), func.sum(sub.c.tax_total),
                       func.sum(sub.c.grand_total), func.sum(sub.c.amount_paid))
                .join(sub, sub.c.supplier_id == Supplier.id)
                .group_by(Supplier.id, Supplier.name)).all()
        rows = []
        for name, cnt, tax, total, paid in data:
            # subquery columns keep their Money type, so SUM returns Decimal
            tax, total, paid = (x or ZERO for x in (tax, total, paid))
            rows.append({"supplier": name, "count": cnt, "tax": tax, "total": total,
                         "paid": paid, "due": total - paid})
        rows.sort(key=lambda r: r["total"], reverse=True)
        totals = {"supplier": "Total", "count": sum(r["count"] for r in rows)}
        for k in ("tax", "total", "paid", "due"):
            totals[k] = sum((r[k] for r in rows), ZERO)
        return ReportResult("Supplier-wise Purchases", [
            Col("supplier", "Supplier"), Col("count", "Purchases", "int"),
            Col("tax", "Tax", "money"), Col("total", "Total", "money"),
            Col("paid", "Paid", "money"), Col("due", "Due", "money")], rows, totals)

    def product_purchases(self, actor: CurrentUser, date_from: date, date_to: date,
                          supplier_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS)
        with self.db.session() as s:
            ids = select(self._purchase_q(date_from, date_to, supplier_id).subquery().c.id)
            data = s.execute(
                select(PurchaseItem.product_name, func.sum(PurchaseItem.quantity),
                       func.sum(PurchaseItem.taxable_amount), func.sum(PurchaseItem.tax_amount),
                       func.sum(PurchaseItem.line_total))
                .where(PurchaseItem.purchase_id.in_(ids))
                .group_by(PurchaseItem.product_id, PurchaseItem.product_name)).all()
        rows = [{"product": n, "qty": q or ZERO, "taxable": t or ZERO, "tax": tx or ZERO,
                 "total": tot or ZERO} for n, q, t, tx, tot in data]
        rows.sort(key=lambda r: r["total"], reverse=True)
        totals = {"product": "Total"}
        for k in ("qty", "taxable", "tax", "total"):
            totals[k] = sum((r[k] for r in rows), ZERO)
        return ReportResult("Product-wise Purchases", [
            Col("product", "Product"), Col("qty", "Quantity", "qty"),
            Col("taxable", "Taxable", "money"), Col("tax", "Tax", "money"),
            Col("total", "Total", "money")], rows, totals)

    # =========================== EXPENSES =======================================
    def _expense_q(self, date_from, date_to, category_id=None):
        if date_to < date_from:
            raise ValidationError("The end date must be on or after the start date.")
        q = select(Expense).where(Expense.is_void.is_(False), Expense.expense_date >= date_from,
                                  Expense.expense_date <= date_to)
        if category_id:
            q = q.where(Expense.category_id == category_id)
        return q

    def expense_register(self, actor: CurrentUser, date_from: date, date_to: date,
                         category_id: int | None = None) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS, Perm.VIEW_EXPENSES)
        with self.db.session() as s:
            rows = [{"date": e.expense_date, "category": e.category.name, "amount": e.amount,
                     "method": e.method_name or "", "description": e.description or "",
                     "reference": e.reference or ""}
                    for e in s.scalars(self._expense_q(date_from, date_to, category_id)
                                       .order_by(Expense.expense_date, Expense.id))]
        return ReportResult("Expense Register", [
            Col("date", "Date", "date"), Col("category", "Category"),
            Col("amount", "Amount", "money"), Col("method", "Paid by"),
            Col("description", "Description"), Col("reference", "Reference")], rows,
            {"date": "Total", "amount": sum((r["amount"] for r in rows), ZERO)})

    def expense_by_category(self, actor: CurrentUser, date_from: date,
                            date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_REPORTS, Perm.VIEW_EXPENSES)
        with self.db.session() as s:
            sub = self._expense_q(date_from, date_to).subquery()
            data = s.execute(select(ExpenseCategory.name, func.count(sub.c.id),
                                    func.sum(sub.c.amount))
                             .join(sub, sub.c.category_id == ExpenseCategory.id)
                             .group_by(ExpenseCategory.id, ExpenseCategory.name)).all()
        rows = [{"category": n, "count": c, "amount": a or ZERO} for n, c, a in data]
        rows.sort(key=lambda r: r["amount"], reverse=True)
        total = sum((r["amount"] for r in rows), ZERO)
        for r in rows:
            r["share"] = (r["amount"] * 100 / total) if total else ZERO
        return ReportResult("Expenses by Category", [
            Col("category", "Category"), Col("count", "Entries", "int"),
            Col("amount", "Amount", "money"), Col("share", "Share", "pct")], rows,
            {"category": "Total", "count": sum(r["count"] for r in rows), "amount": total})

    # =========================== FINANCIAL ======================================
    def profit_loss_figures(self, s, date_from: date, date_to: date) -> dict:
        start, end = _rng(date_from, date_to)
        sale_f = and_(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= start,
                      Sale.created_at < end)
        z = lambda x: x or ZERO  # noqa: E731
        taxable, tax, round_off, cost, gross_total, count = s.execute(
            select(func.sum(Sale.taxable_total), func.sum(Sale.tax_total),
                   func.sum(Sale.round_off), func.sum(Sale.cost_total),
                   func.sum(Sale.grand_total), func.count(Sale.id)).where(sale_f)).one()
        r_taxable, r_tax, r_refund, r_cost, r_round_off = s.execute(
            select(func.sum(SaleReturn.taxable_total), func.sum(SaleReturn.tax_total),
                   func.sum(SaleReturn.refund_total), func.sum(SaleReturn.cost_total),
                   func.sum(SaleReturn.round_off))
            .where(SaleReturn.created_at >= start, SaleReturn.created_at < end)).one()
        expenses = s.scalar(select(func.sum(Expense.amount)).where(
            Expense.is_void.is_(False), Expense.expense_date >= date_from,
            Expense.expense_date <= date_to))
        p_sub, p_disc, p_tax, p_total = s.execute(
            select(func.sum(Purchase.subtotal), func.sum(Purchase.discount_total),
                   func.sum(Purchase.tax_total), func.sum(Purchase.grand_total))
            .where(Purchase.status == PurchaseStatus.COMPLETED,
                   Purchase.purchase_date >= date_from, Purchase.purchase_date <= date_to)).one()
        p_taxable = z(p_sub) - z(p_disc)
        round_off = z(round_off) - z(r_round_off)  # net of round-off refunded on returns
        net_sales = z(taxable) - z(r_taxable) + round_off
        cogs = z(cost) - z(r_cost)
        gross_profit = net_sales - cogs
        net = gross_profit - z(expenses)
        return {
            "invoice_count": count or 0, "sales_taxable": z(taxable), "returns_taxable": z(r_taxable),
            "round_off": z(round_off), "net_sales": net_sales, "cogs": cogs,
            "gross_profit": gross_profit, "expenses": z(expenses), "net_profit": net,
            "sales_total": z(gross_total), "refund_total": z(r_refund),
            "gst_collected": z(tax) - z(r_tax), "purchases_total": z(p_total),
            "purchases_taxable": z(p_taxable), "purchases_tax": z(p_tax),
        }

    def profit_loss(self, actor: CurrentUser, date_from: date, date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_FINANCIAL_REPORTS)
        with self.db.session() as s:
            f = self.profit_loss_figures(s, date_from, date_to)
        rows = [
            {"item": "Sales (taxable value, excl. tax)", "amount": f["sales_taxable"]},
            {"item": "Less: returns (taxable value)", "amount": -f["returns_taxable"]},
            {"item": "Invoice round-off adjustments", "amount": f["round_off"]},
            {"item": "Net sales (revenue)", "amount": f["net_sales"]},
            {"item": "Less: cost of goods sold", "amount": -f["cogs"]},
            {"item": "Gross profit", "amount": f["gross_profit"]},
            {"item": "Less: operating expenses", "amount": -f["expenses"]},
            {"item": "NET PROFIT / (LOSS)", "amount": f["net_profit"]},
        ]
        summary = [
            ("Completed invoices", str(f["invoice_count"])),
            ("Sales incl. tax", f["sales_total"]), ("Refunds paid", f["refund_total"]),
            ("Tax (GST) collected on sales, net of returns", f["gst_collected"]),
            ("Inventory purchases (completed, incl. tax)", f["purchases_total"]),
            ("Tax on purchases", f["purchases_tax"]),
        ]
        return ReportResult("Profit & Loss", [Col("item", "Item"), Col("amount", "Amount", "money")],
                            rows, None, notes=PROFIT_LOSS_METHOD, summary=summary)

    def revenue_summary(self, actor: CurrentUser, date_from: date, date_to: date) -> ReportResult:
        """Revenue / purchases / expenses side by side, by month."""
        require(actor, Perm.VIEW_FINANCIAL_REPORTS)
        months = []
        cur = date_from.replace(day=1)
        while cur <= date_to:
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            months.append((max(cur, date_from), min(nxt - timedelta(days=1), date_to)))
            cur = nxt
        rows = []
        with self.db.session() as s:
            for a, b in months:
                f = self.profit_loss_figures(s, a, b)
                rows.append({"period": a.strftime("%B %Y"), "revenue": f["net_sales"],
                             "cogs": f["cogs"], "purchases": f["purchases_total"],
                             "expenses": f["expenses"], "net": f["net_profit"]})
        totals = {"period": "Total"}
        for k in ("revenue", "cogs", "purchases", "expenses", "net"):
            totals[k] = sum((r[k] for r in rows), ZERO)
        return ReportResult("Revenue, Purchases & Expenses", [
            Col("period", "Month"), Col("revenue", "Net sales", "money"),
            Col("cogs", "COGS", "money"), Col("purchases", "Purchases", "money"),
            Col("expenses", "Expenses", "money"), Col("net", "Net profit/loss", "money")],
            rows, totals, notes=PROFIT_LOSS_METHOD)

    def payment_summary(self, actor: CurrentUser, date_from: date, date_to: date) -> ReportResult:
        require(actor, Perm.VIEW_FINANCIAL_REPORTS)
        start, end = _rng(date_from, date_to)
        with self.db.session() as s:
            base = and_(Payment.is_void.is_(False), Payment.created_at >= start,
                        Payment.created_at < end)

            def grouped(*conds):
                return dict(s.execute(select(Payment.method_name, func.sum(Payment.amount))
                                      .where(base, *conds).group_by(Payment.method_name)).all())
            receipts = grouped(Payment.direction == PaymentDirection.IN)
            refunds = grouped(Payment.return_id.isnot(None))
            supplier = grouped(Payment.purchase_id.isnot(None))
            exp = dict(s.execute(select(func.coalesce(Expense.method_name, "Not specified"),
                                        func.sum(Expense.amount))
                                 .where(Expense.is_void.is_(False),
                                        Expense.expense_date >= date_from,
                                        Expense.expense_date <= date_to)
                                 .group_by(Expense.method_name)).all())
            order = [m.name for m in s.scalars(select(PaymentMethod)
                                               .order_by(PaymentMethod.sort_order))]
        names = list(dict.fromkeys(order + list(receipts) + list(refunds) + list(supplier)
                                   + list(exp)))
        rows = []
        for n in names:
            r = {"method": n, "receipts": receipts.get(n) or ZERO,
                 "refunds": refunds.get(n) or ZERO, "supplier": supplier.get(n) or ZERO,
                 "expenses": exp.get(n) or ZERO}
            r["net"] = r["receipts"] - r["refunds"] - r["supplier"] - r["expenses"]
            if any(r[k] for k in ("receipts", "refunds", "supplier", "expenses")):
                rows.append(r)
        totals = {"method": "Total"}
        for k in ("receipts", "refunds", "supplier", "expenses", "net"):
            totals[k] = sum((r[k] for r in rows), ZERO)
        return ReportResult("Payment-method Summary", [
            Col("method", "Method"), Col("receipts", "Sales receipts", "money"),
            Col("refunds", "Customer refunds", "money"),
            Col("supplier", "Supplier payments", "money"),
            Col("expenses", "Expenses paid", "money"),
            Col("net", "Net recorded flow", "money")], rows, totals,
            notes=["Recorded amounts only, based on what users entered. These are not bank or "
                   "cash-drawer balances; no bank reconciliation is performed."])
