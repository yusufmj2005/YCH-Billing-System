from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout

from app.config.constants import Perm, SaleStatus
from app.reports.base import Col
from app.ui import documents
from app.ui.dialogs.sale_detail_dialog import SaleDetailDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import DateRangeBar, button, label, search_box, ui_action
from app.ui.widgets.table import DataTable

PAGE = 100


class SalesPage(Page):
    invoice_mode = False

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Invoice no., customer name or phone…",
                                 lambda: self.load(0))
        self.range = DateRangeBar("this_month")
        self.range.changed.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.range)
        self.status = QComboBox()
        self.status.addItem("All statuses", None)
        self.status.addItem("Completed", SaleStatus.COMPLETED)
        self.status.addItem("Voided", SaleStatus.VOIDED)
        self.status.currentIndexChanged.connect(lambda: self.load(0))
        self.method = QComboBox()
        self.method.addItem("All payment methods", None)
        for pm in ctx.services.payment_methods.list(include_inactive=True):
            self.method.addItem(pm["name"], pm["id"])
        self.method.currentIndexChanged.connect(lambda: self.load(0))
        self.customer = QComboBox()
        self.customer.addItem("All customers", None)
        if ctx.can(Perm.VIEW_CUSTOMERS):
            for c in ctx.services.partners.list_customers(ctx.user, include_inactive=True):
                self.customer.addItem(c["name"], c["id"])
        self.customer.currentIndexChanged.connect(lambda: self.load(0))
        bar.addWidget(self.status)
        bar.addWidget(self.method)
        bar.addWidget(self.customer)
        bar.addStretch(1)
        self.root.addLayout(bar)

        cols = [Col("invoice_no", "Invoice"), Col("created_at", "Date", "datetime"),
                Col("customer", "Customer"), Col("items", "Items", "int"),
                Col("discount", "Discount", "money"), Col("tax_total", "Tax", "money"),
                Col("grand_total", "Total", "money"), Col("refunded", "Refunded", "money"),
                Col("payment_methods", "Paid by"), Col("status_txt", "Status"),
                Col("cashier", "User")]
        self.table = DataTable(cols, page_size=PAGE, stretch="customer")
        self.table.set_row_color(lambda r: C["faint"] if r["status"] == SaleStatus.VOIDED else None)
        self.table.activated.connect(self.view_sale)
        self.table.pageRequested.connect(self.load)
        self.root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.summary = label("", "Muted")
        actions.addWidget(self.summary)
        actions.addStretch(1)
        actions.addWidget(button("View details", None, lambda: self.view_sale(self.table.selected())))
        actions.addWidget(button("Print", None, self.print_selected))
        actions.addWidget(button("Open PDF", None, self.open_selected))
        actions.addWidget(button("Save PDF as…", None, self.save_selected))
        self.root.addLayout(actions)

    def on_show(self) -> None:
        self.load(0)

    @ui_action
    def load(self, offset: int = 0) -> None:
        a, b = self.range.range()
        rows, total = self.ctx.services.sales.list_sales(
            self.ctx.user, date_from=a, date_to=b, status=self.status.currentData(),
            payment_method_id=self.method.currentData(),
            customer_id=self.customer.currentData(), search=self.search.text(),
            limit=PAGE, offset=offset)
        for r in rows:
            r["status_txt"] = r["status"].title()
        self.table.set_rows(rows, total, offset)
        done = [r for r in rows if r["status"] == SaleStatus.COMPLETED]
        if total <= PAGE:
            amt = sum((r["grand_total"] for r in done), 0)
            self.summary.setText(f"{len(done)} completed sale(s) totalling {self.ctx.money(amt)}"
                                 f" • {self.range.description()}")
        else:
            self.summary.setText(f"{total} sale(s) • {self.range.description()}")

    def _sel(self):
        r = self.table.selected()
        if r is None:
            from app.ui.widgets.common import show_info
            show_info(self, "Select a sale first.")
        return r

    def view_sale(self, row) -> None:
        if row:
            dlg = SaleDetailDialog(self, self.ctx, row["id"])
            dlg.exec()
            if dlg.changed:
                self.load(self.table.offset)

    @ui_action
    def print_selected(self):
        r = self._sel()
        if r and documents.print_invoice(self.ctx, self, r["id"]):
            self.ctx.toast("Invoice sent to printer")

    @ui_action
    def open_selected(self):
        r = self._sel()
        if r:
            documents.open_invoice(self.ctx, self, r["id"])

    @ui_action
    def save_selected(self):
        r = self._sel()
        if r:
            documents.save_invoice_as(self.ctx, self, r["id"])


class InvoicesPage(SalesPage):
    """Same data as Sales, focused on finding and reprinting invoices."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.range.preset.setCurrentIndex(self.range.preset.findData("last_30"))
        self.search.setPlaceholderText("Type or scan an invoice number…")
        self.search.returnPressed.connect(self.open_exact)
        for w in (self.method, self.customer):
            w.hide()

    @ui_action
    def open_exact(self):
        text = self.search.text().strip()
        if not text:
            return
        try:
            sale = self.ctx.services.sales.get_sale(self.ctx.user, invoice_no=text)
        except Exception:
            return
        self.view_sale({"id": sale["id"]})
