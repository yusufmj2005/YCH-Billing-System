"""Dashboard figures (all aggregated from the database; zero when empty)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select

from app.config.constants import PaymentDirection, Perm, PurchaseStatus, SaleStatus
from app.database.database import Database
from app.models import Expense, Payment, PaymentMethod, Product, Purchase, Sale, SaleReturn
from app.security.auth import CurrentUser, require
from app.services.inventory_service import InventoryService, low_stock_condition
from app.services.settings_service import get_settings
from app.utils.dates import day_end_exclusive, day_start
from app.utils.money import ZERO


class DashboardService:
    def __init__(self, db: Database):
        self.db = db

    def overview(self, actor: CurrentUser, date_from: date, date_to: date) -> dict:
        require(actor, Perm.VIEW_DASHBOARD)
        start, end = day_start(date_from), day_end_exclusive(date_to)
        with self.db.session() as s:
            completed = and_(Sale.status == SaleStatus.COMPLETED, Sale.created_at >= start,
                             Sale.created_at < end)
            sales_total, sales_count = s.execute(
                select(func.sum(Sale.grand_total), func.count(Sale.id)).where(completed)).one()
            refunds = s.scalar(select(func.sum(SaleReturn.refund_total)).where(
                SaleReturn.created_at >= start, SaleReturn.created_at < end))
            expenses = s.scalar(select(func.sum(Expense.amount)).where(
                Expense.is_void.is_(False), Expense.expense_date >= date_from,
                Expense.expense_date <= date_to))
            pay_base = and_(Payment.is_void.is_(False), Payment.created_at >= start,
                            Payment.created_at < end)
            received = dict(s.execute(select(Payment.payment_method_id, func.sum(Payment.amount))
                                      .where(pay_base, Payment.direction == PaymentDirection.IN)
                                      .group_by(Payment.payment_method_id)).all())
            refunded = dict(s.execute(select(Payment.payment_method_id, func.sum(Payment.amount))
                                      .where(pay_base, Payment.return_id.isnot(None))
                                      .group_by(Payment.payment_method_id)).all())
            methods = []
            for m in s.scalars(select(PaymentMethod).order_by(PaymentMethod.sort_order)):
                r, f = received.get(m.id) or ZERO, refunded.get(m.id) or ZERO
                if m.is_active or r or f:
                    methods.append({"name": m.name, "kind": m.kind, "received": r,
                                    "refunded": f, "net": r - f})

            recent_sales = [{
                "id": x.id, "invoice_no": x.invoice_no, "created_at": x.created_at,
                "customer": x.customer_name or "Walk-in", "grand_total": x.grand_total,
                "status": x.status} for x in s.scalars(select(Sale).order_by(Sale.id.desc())
                                                       .limit(8))]
            recent_purchases = [{
                "id": p.id, "purchase_no": p.purchase_no, "purchase_date": p.purchase_date,
                "supplier": p.supplier.name, "grand_total": p.grand_total, "status": p.status}
                for p in s.scalars(select(Purchase).where(
                    Purchase.status != PurchaseStatus.DRAFT)
                    .order_by(Purchase.id.desc()).limit(8))]
            threshold = Decimal(str(get_settings(s).get("low_stock_threshold") or "0"))
            low = [{"id": p.id, "name": p.name, "stock": p.current_stock, "unit": p.unit,
                    "min": p.min_stock_level if p.min_stock_level is not None else threshold}
                   for p in s.scalars(select(Product).where(
                       Product.is_active.is_(True), low_stock_condition(threshold))
                       .order_by(Product.current_stock, Product.name).limit(10))]

            # daily sales trend for the 14 days ending on date_to
            trend_start = date_to - timedelta(days=13)
            day = func.date(Sale.created_at)
            trend_rows = dict(s.execute(select(day, func.sum(Sale.grand_total))
                                        .where(Sale.status == SaleStatus.COMPLETED,
                                               Sale.created_at >= day_start(trend_start),
                                               Sale.created_at < end).group_by(day)).all())
            trend = []
            for i in range(14):
                d = trend_start + timedelta(days=i)
                trend.append((d, trend_rows.get(d.isoformat()) or ZERO))

        inv = InventoryService(self.db).summary()
        return {
            "sales_total": sales_total or ZERO, "sales_count": sales_count or 0,
            "refunds": refunds or ZERO, "expenses": expenses or ZERO,
            "inventory_value": inv["inventory_value"], "active_products": inv["active_products"],
            "low_stock_count": inv["low_stock"], "low_stock": low,
            "payment_methods": methods, "recent_sales": recent_sales,
            "recent_purchases": recent_purchases, "trend": trend,
        }
