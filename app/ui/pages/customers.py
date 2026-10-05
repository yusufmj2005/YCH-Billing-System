from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.dialogs.customer_picker import CUSTOMER_FIELDS
from app.ui.dialogs.simple_list_dialog import ListDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import button, search_box, show_info, ui_action
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

FIELDS = CUSTOMER_FIELDS + [Field("is_active", "Active", "check")]


class CustomersPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Search name, phone or email…", self.load)
        self.inactive = QCheckBox("Show inactive")
        self.inactive.toggled.connect(self.load)
        bar.addWidget(self.search)
        bar.addWidget(self.inactive)
        bar.addStretch(1)
        if ctx.can(Perm.EDIT_CUSTOMERS):
            bar.addWidget(button("New customer", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([Col("name", "Customer"), Col("phone", "Phone"),
                                Col("email", "Email"), Col("gstin", "GSTIN"),
                                Col("created_at", "Added", "date"), Col("status", "Status")],
                               stretch="name")
        self.table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.table.activated.connect(lambda r: self.history())
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        act.addStretch(1)
        act.addWidget(button("Purchase history", None, self.history))
        if ctx.can(Perm.EDIT_CUSTOMERS):
            act.addWidget(button("Edit", None, lambda: self.edit(self.table.selected())))
        self.root.addLayout(act)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        rows = self.ctx.services.partners.list_customers(self.ctx.user, self.search.text(),
                                                        self.inactive.isChecked(), limit=1000)
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.table.set_rows(rows)

    def new(self):
        if FormDialog(self, "New customer", FIELDS, {"is_active": True},
                      lambda d: self.ctx.services.partners.save_customer(self.ctx.user, None, d),
                      width=520).exec():
            self.load()

    def edit(self, row):
        if not row:
            show_info(self, "Select a customer first.")
            return
        if FormDialog(self, "Edit customer", FIELDS, row,
                      lambda d: self.ctx.services.partners.save_customer(self.ctx.user, row["id"],
                                                                         d), width=520).exec():
            self.load()

    @ui_action
    def history(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a customer first.")
            return
        h = self.ctx.services.partners.customer_history(self.ctx.user, r["id"])
        ListDialog(self, f"Purchase history — {r['name']}", [
            Col("invoice_no", "Invoice"), Col("created_at", "Date", "datetime"),
            Col("items", "Lines", "int"), Col("grand_total", "Total", "money"),
            Col("refunded", "Refunded", "money"), Col("status", "Status")], h["sales"],
            subtitle=f"{h['invoice_count']} completed invoice(s) • net spent "
                     f"{self.ctx.money(h['total_spent'])}").exec()
