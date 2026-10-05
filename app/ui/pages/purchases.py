from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog

from app.config.constants import Perm, PurchaseStatus
from app.reports.base import Col
from app.ui.dialogs.purchase_dialog import PurchaseDialog
from app.ui.dialogs.simple_list_dialog import ListDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import (DateRangeBar, button, confirm, label, search_box, show_info,
                                   ui_action)
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable
from app.utils.dates import fmt_date

PAGE = 100


class PurchasesPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Purchase no., supplier invoice or supplier…",
                                 lambda: self.load(0))
        self.range = DateRangeBar("this_month")
        self.range.changed.connect(lambda: self.load(0))
        self.supplier = QComboBox()
        self.status = QComboBox()
        self.status.addItem("All statuses", None)
        for s in (PurchaseStatus.DRAFT, PurchaseStatus.COMPLETED, PurchaseStatus.CANCELLED):
            self.status.addItem(s.title(), s)
        for w in (self.supplier, self.status):
            w.currentIndexChanged.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.range)
        bar.addWidget(self.supplier)
        bar.addWidget(self.status)
        bar.addStretch(1)
        if ctx.can(Perm.CREATE_PURCHASE):
            bar.addWidget(button("New purchase", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([
            Col("purchase_no", "Purchase"), Col("purchase_date", "Date", "date"),
            Col("supplier", "Supplier"), Col("supplier_invoice_no", "Supplier invoice"),
            Col("items", "Lines", "int"), Col("grand_total", "Total", "money"),
            Col("amount_paid", "Paid", "money"), Col("balance", "Due", "money"),
            Col("payment_status", "Payment"), Col("status", "Status")],
            page_size=PAGE, stretch="supplier")
        self.table.set_row_color(lambda r: C["faint"] if r["status"] == PurchaseStatus.CANCELLED
                                 else C["primary"] if r["status"] == PurchaseStatus.DRAFT else None)
        self.table.activated.connect(self.open)
        self.table.pageRequested.connect(self.load)
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        act.addWidget(label("Drafts do not affect stock until completed.", "Faint"))
        act.addStretch(1)
        act.addWidget(button("Open", None, lambda: self.open(self.table.selected())))
        if ctx.can(Perm.CREATE_PURCHASE):
            act.addWidget(button("Complete draft", None, self.complete))
            act.addWidget(button("Discard draft", None, self.discard))
            act.addWidget(button("Record payment", None, self.pay))
        if ctx.can(Perm.CANCEL_PURCHASE):
            act.addWidget(button("Cancel purchase", "danger", self.cancel))
        self.root.addLayout(act)

    def on_show(self):
        cur = self.supplier.currentData()
        self.supplier.blockSignals(True)
        self.supplier.clear()
        self.supplier.addItem("All suppliers", None)
        for s in self.ctx.services.partners.list_suppliers(self.ctx.user, include_inactive=True):
            self.supplier.addItem(s["name"], s["id"])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(cur)))
        self.supplier.blockSignals(False)
        self.load(0)

    @ui_action
    def load(self, offset: int = 0):
        a, b = self.range.range()
        rows, total = self.ctx.services.purchases.list_purchases(
            self.ctx.user, date_from=a, date_to=b, supplier_id=self.supplier.currentData(),
            status=self.status.currentData(), search=self.search.text(), limit=PAGE,
            offset=offset)
        self.table.set_rows(rows, total, offset)

    def _sel(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a purchase first.")
        return r

    @ui_action
    def new(self):
        if PurchaseDialog(self, self.ctx).exec():
            self.load(0)

    @ui_action
    def open(self, row):
        if not row:
            return
        p = self.ctx.services.purchases.get_purchase(self.ctx.user, row["id"])
        if p["status"] == PurchaseStatus.DRAFT and self.ctx.can(Perm.CREATE_PURCHASE):
            if PurchaseDialog(self, self.ctx, p).exec():
                self.load(self.table.offset)
            return
        m = self.ctx.money
        sub = (f"{p['supplier']} • {fmt_date(p['purchase_date'])} • "
               f"Supplier invoice: {p['supplier_invoice_no'] or '—'} • "
               f"Status: {p['status'].title()} • Total {m(p['grand_total'])} • "
               f"Paid {m(p['amount_paid'])}")
        if p["cancel_reason"]:
            sub += f" • Cancelled: {p['cancel_reason']}"
        ListDialog(self, f"Purchase {p['purchase_no']}", [
            Col("product_name", "Product"), Col("quantity", "Qty", "qty"),
            Col("unit_cost", "Unit cost", "money"), Col("discount_amount", "Discount", "money"),
            Col("taxable_amount", "Taxable", "money"), Col("tax_rate", "Tax %", "pct"),
            Col("tax_amount", "Tax", "money"), Col("line_total", "Total", "money")],
            p["items"], subtitle=sub, stretch="product_name",
            extra_sections=[("Supplier payments", [
                Col("created_at", "Date", "datetime"), Col("method", "Method"),
                Col("amount", "Amount", "money"), Col("reference", "Reference"),
                Col("is_void", "Void", "bool")], p["payments"])]).exec()

    @ui_action
    def complete(self):
        r = self._sel()
        if not r:
            return
        if r["status"] != PurchaseStatus.DRAFT:
            show_info(self, "Only drafts can be completed.")
            return
        if confirm(self, f"Complete {r['purchase_no']} and add its items to stock?"):
            self.ctx.services.purchases.complete(self.ctx.user, r["id"])
            self.ctx.toast("Purchase completed; stock updated")
            self.load(self.table.offset)

    @ui_action
    def discard(self):
        r = self._sel()
        if not r:
            return
        if r["status"] != PurchaseStatus.DRAFT:
            show_info(self, "Only drafts can be discarded. Use 'Cancel purchase' for completed "
                            "purchases.")
            return
        if confirm(self, f"Discard draft {r['purchase_no']}?", danger=True, yes_text="Discard"):
            self.ctx.services.purchases.discard_draft(self.ctx.user, r["id"])
            self.load(self.table.offset)

    @ui_action
    def cancel(self):
        r = self._sel()
        if not r:
            return
        if r["status"] != PurchaseStatus.COMPLETED:
            show_info(self, "Only completed purchases can be cancelled.")
            return
        reason, ok = QInputDialog.getText(
            self, "Cancel purchase", f"Cancel {r['purchase_no']}?\n\nThe purchased quantities "
            "will be removed from stock and recorded supplier payments marked void.\n\n"
            "Reason (required):")
        if ok and confirm(self, "Cancel this purchase? This cannot be undone.", danger=True,
                          yes_text="Cancel purchase"):
            self.ctx.services.purchases.cancel(self.ctx.user, r["id"], reason)
            self.ctx.toast("Purchase cancelled; stock reversed")
            self.load(self.table.offset)

    @ui_action
    def pay(self):
        r = self._sel()
        if not r:
            return
        if r["status"] != PurchaseStatus.COMPLETED:
            show_info(self, "Payments can be recorded for completed purchases only.")
            return
        if r["balance"] <= 0:
            show_info(self, "This purchase is fully paid.")
            return
        methods = [(m["name"], m["id"]) for m in self.ctx.services.payment_methods.list()]
        FormDialog(self, f"Record payment — {r['purchase_no']}", [
            Field("method", "Payment method", "combo", required=True, options=methods),
            Field("amount", "Amount", "money", required=True,
                  help=f"Balance due: {self.ctx.money(r['balance'])}"),
            Field("reference", "Transaction / Reference ID"),
            Field("description", "Description")], {"amount": f"{r['balance']:.2f}"},
            on_submit=lambda d: self.ctx.services.purchases.record_payment(
                self.ctx.user, r["id"], d["method"], d["amount"], d["reference"],
                d["description"]), submit_text="Record payment").exec()
        self.load(self.table.offset)
