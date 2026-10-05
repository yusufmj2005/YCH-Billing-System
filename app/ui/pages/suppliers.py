from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.dialogs.purchase_dialog import SUPPLIER_FIELDS
from app.ui.dialogs.simple_list_dialog import ListDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import button, search_box, show_info, ui_action
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

FIELDS = SUPPLIER_FIELDS + [Field("is_active", "Active", "check")]


class SuppliersPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Search name, contact, phone or GSTIN…", self.load)
        self.inactive = QCheckBox("Show inactive")
        self.inactive.toggled.connect(self.load)
        bar.addWidget(self.search)
        bar.addWidget(self.inactive)
        bar.addStretch(1)
        if ctx.can(Perm.EDIT_SUPPLIERS):
            bar.addWidget(button("New supplier", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([Col("name", "Supplier"), Col("contact_person", "Contact"),
                                Col("phone", "Phone"), Col("email", "Email"),
                                Col("gstin", "GSTIN"), Col("status", "Status")], stretch="name")
        self.table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.table.activated.connect(self.edit)
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        act.addStretch(1)
        act.addWidget(button("Purchase history", None, self.history))
        if ctx.can(Perm.EDIT_SUPPLIERS):
            act.addWidget(button("Edit", None, lambda: self.edit(self.table.selected())))
        self.root.addLayout(act)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        rows = self.ctx.services.partners.list_suppliers(self.ctx.user, self.search.text(),
                                                        self.inactive.isChecked())
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.table.set_rows(rows)

    def new(self):
        if FormDialog(self, "New supplier", FIELDS, {"is_active": True},
                      lambda d: self.ctx.services.partners.save_supplier(self.ctx.user, None, d),
                      width=520).exec():
            self.load()

    def edit(self, row):
        if not row or not self.ctx.can(Perm.EDIT_SUPPLIERS):
            return
        if FormDialog(self, "Edit supplier", FIELDS, row,
                      lambda d: self.ctx.services.partners.save_supplier(self.ctx.user, row["id"],
                                                                         d), width=520).exec():
            self.load()

    @ui_action
    def history(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a supplier first.")
            return
        h = self.ctx.services.partners.supplier_history(self.ctx.user, r["id"])
        ListDialog(self, f"Purchase history — {r['name']}", [
            Col("purchase_no", "Purchase"), Col("purchase_date", "Date", "date"),
            Col("supplier_invoice_no", "Supplier invoice"), Col("status", "Status"),
            Col("grand_total", "Total", "money"), Col("amount_paid", "Paid", "money"),
            Col("payment_status", "Payment")], h["purchases"],
            extra_sections=[("Products purchased (completed purchases)", [
                Col("product", "Product"), Col("quantity", "Quantity", "qty"),
                Col("total", "Total", "money"), Col("last_purchase", "Last purchased", "date")],
                h["products"])]).exec()
