from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.chart import BarChart
from app.ui.widgets.common import (Card, DateRangeBar, StatCard, button, clear_layout, label,
                                   ui_action)
from app.ui.widgets.table import DataTable
from app.utils.money import fmt_qty


class DashboardPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setObjectName("Page")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(14)
        scroll.setWidget(body)
        self.root.addWidget(scroll)

        top = QHBoxLayout()
        self.range = DateRangeBar("today")
        self.range.changed.connect(self.refresh)
        top.addWidget(label("Period:", "Muted"))
        top.addWidget(self.range)
        top.addStretch(1)
        self.period_note = label("", "Faint")
        top.addWidget(self.period_note)
        top.addWidget(button("Refresh", None, self.refresh))
        lay.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.c_sales = StatCard("Sales")
        self.c_count = StatCard("Transactions")
        self.c_exp = StatCard("Expenses")
        self.c_refunds = StatCard("Refunds")
        self.c_inv = StatCard("Inventory value (at cost)")
        self.c_products = StatCard("Active products")
        self.c_low = StatCard("Low-stock products")
        for i, c in enumerate((self.c_sales, self.c_count, self.c_exp, self.c_refunds,
                               self.c_inv, self.c_products, self.c_low)):
            grid.addWidget(c, i // 4, i % 4)
        lay.addLayout(grid)

        # payment methods
        pay_card = Card()
        pay_card.lay.addWidget(label("Recorded payments by method", "SectionTitle"))
        pay_card.lay.addWidget(label("Receipts minus refunds recorded in the period. "
                                     "These are recorded amounts, not bank balances.", "Faint"))
        self.pay_grid = QGridLayout()
        self.pay_grid.setSpacing(10)
        pay_card.lay.addLayout(self.pay_grid)
        lay.addWidget(pay_card)

        mid = QHBoxLayout()
        mid.setSpacing(12)
        chart_card = Card()
        chart_card.lay.addWidget(label("Daily sales — 14 days ending on the period end",
                                       "SectionTitle"))
        self.chart = BarChart()
        chart_card.lay.addWidget(self.chart)
        mid.addWidget(chart_card, 3)
        low_card = Card()
        low_card.lay.addWidget(label("Low stock", "SectionTitle"))
        self.low_table = DataTable([Col("name", "Product"), Col("stock_txt", "In stock", "text"),
                                    Col("min", "Min", "qty")], stretch="name")
        self.low_table.setMinimumHeight(200)
        low_card.lay.addWidget(self.low_table)
        if ctx.can(Perm.VIEW_INVENTORY):
            low_card.lay.addWidget(button("Open inventory", "ghost",
                                          lambda: ctx.navigate("inventory")))
        mid.addWidget(low_card, 2)
        lay.addLayout(mid)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        s_card = Card()
        s_card.lay.addWidget(label("Recent sales", "SectionTitle"))
        self.sales_table = DataTable([Col("invoice_no", "Invoice"),
                                      Col("created_at", "Date", "datetime"),
                                      Col("customer", "Customer"),
                                      Col("grand_total", "Total", "money"),
                                      Col("status", "Status")], stretch="customer")
        self.sales_table.setMinimumHeight(230)
        self.sales_table.set_row_color(lambda r: C["faint"] if r["status"] == "VOIDED" else None)
        s_card.lay.addWidget(self.sales_table)
        bottom.addWidget(s_card, 1)
        p_card = Card()
        p_card.lay.addWidget(label("Recent purchases", "SectionTitle"))
        self.purch_table = DataTable([Col("purchase_no", "Purchase"),
                                      Col("purchase_date", "Date", "date"),
                                      Col("supplier", "Supplier"),
                                      Col("grand_total", "Total", "money"),
                                      Col("status", "Status")], stretch="supplier")
        self.purch_table.setMinimumHeight(230)
        p_card.lay.addWidget(self.purch_table)
        bottom.addWidget(p_card, 1)
        lay.addLayout(bottom)

    def on_show(self) -> None:
        self.refresh()

    @ui_action
    def refresh(self) -> None:
        a, b = self.range.range()
        d = self.ctx.services.dashboard.overview(self.ctx.user, a, b)
        m = self.ctx.money
        self.period_note.setText(self.range.description())
        self.c_sales.set(m(d["sales_total"]), "Completed sales incl. tax")
        self.c_count.set(str(d["sales_count"]), "Completed invoices")
        self.c_exp.set(m(d["expenses"]), "Recorded, non-void")
        self.c_refunds.set(m(d["refunds"]), "Customer returns")
        self.c_inv.set(m(d["inventory_value"]), "Current stock × cost price")
        self.c_products.set(str(d["active_products"]), "")
        self.c_low.set(str(d["low_stock_count"]), "At or below minimum level")
        self.c_low.value.setStyleSheet(f"color: {C['warning']};" if d["low_stock_count"] else "")

        clear_layout(self.pay_grid)
        for i, pm in enumerate(d["payment_methods"]):
            card = StatCard(f"Recorded {pm['name']}")
            card.set(m(pm["net"]), f"Received {m(pm['received'])}"
                     + (f"  •  Refunded {m(pm['refunded'])}" if pm["refunded"] else ""))
            card.value.setStyleSheet("font-size: 14pt;")
            self.pay_grid.addWidget(card, i // 6, i % 6)

        self.chart.set_points(d["trend"])
        for r in d["low_stock"]:
            r["stock_txt"] = f"{fmt_qty(r['stock'])} {r['unit']}"
        self.low_table.set_rows(d["low_stock"])
        self.sales_table.set_rows(d["recent_sales"])
        self.purch_table.set_rows(d["recent_purchases"])
