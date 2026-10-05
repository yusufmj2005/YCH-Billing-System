from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QInputDialog

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.dialogs.simple_list_dialog import ListDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import (DateRangeBar, button, confirm, label, search_box, show_info,
                                   ui_action)
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

PAGE = 200


class ExpensesPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Description or reference…", lambda: self.load(0))
        self.range = DateRangeBar("this_month")
        self.range.changed.connect(lambda: self.load(0))
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(lambda: self.load(0))
        self.void = QCheckBox("Include void")
        self.void.toggled.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.range)
        bar.addWidget(self.category)
        bar.addWidget(self.void)
        bar.addStretch(1)
        if ctx.can(Perm.CREATE_EXPENSE):
            bar.addWidget(button("Record expense", "primary", self.new))
        self.root.addLayout(bar)
        self.table = DataTable([
            Col("expense_date", "Date", "date"), Col("category", "Category"),
            Col("amount", "Amount", "money"), Col("method", "Paid by"),
            Col("description", "Description"), Col("reference", "Reference"),
            Col("user", "Recorded by"), Col("state", "Status")], page_size=PAGE,
            stretch="description")
        self.table.set_row_color(lambda r: C["faint"] if r["is_void"] else None)
        self.table.pageRequested.connect(self.load)
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        self.total = label("", "SectionTitle")
        act.addWidget(self.total)
        act.addStretch(1)
        if ctx.can(Perm.VOID_EXPENSE):
            act.addWidget(button("Manage categories", None, self.categories))
            act.addWidget(button("Void expense", "danger", self.void_selected))
        self.root.addLayout(act)

    def on_show(self):
        cur = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for c in self.ctx.services.expenses.list_categories(include_inactive=True):
            self.category.addItem(c["name"], c["id"])
        self.category.setCurrentIndex(max(0, self.category.findData(cur)))
        self.category.blockSignals(False)
        self.load(0)

    @ui_action
    def load(self, offset: int = 0):
        a, b = self.range.range()
        rows, total, amount = self.ctx.services.expenses.list_expenses(
            self.ctx.user, date_from=a, date_to=b, category_id=self.category.currentData(),
            include_void=self.void.isChecked(), search=self.search.text(), limit=PAGE,
            offset=offset)
        for r in rows:
            r["state"] = f"Void: {r['void_reason']}" if r["is_void"] else (
                "From payroll" if r["from_payroll"] else "Recorded")
        self.table.set_rows(rows, total, offset)
        self.total.setText(f"Total (non-void): {self.ctx.money(amount)}  •  "
                           f"{self.range.description()}")

    def new(self):
        cats = [(c["name"], c["id"]) for c in self.ctx.services.expenses.list_categories()]
        methods = [("— Not specified —", None)] + [
            (m["name"], m["id"]) for m in self.ctx.services.payment_methods.list()]
        if FormDialog(self, "Record expense", [
                Field("category_id", "Category", "combo", required=True, options=cats),
                Field("amount", "Amount", "money", required=True),
                Field("expense_date", "Date", "date", required=True),
                Field("payment_method_id", "Paid by", "combo", options=methods),
                Field("description", "Description", "multiline"),
                Field("reference", "Reference / bill no.")], {"expense_date": date.today()},
                lambda d: self.ctx.services.expenses.create_expense(self.ctx.user, d)).exec():
            self.ctx.toast("Expense recorded")
            self.load(0)

    @ui_action
    def void_selected(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select an expense first.")
            return
        if r["is_void"]:
            show_info(self, "This expense is already void.")
            return
        reason, ok = QInputDialog.getText(self, "Void expense",
                                          "Reason for voiding this expense (required):")
        if ok and confirm(self, f"Void the {self.ctx.money(r['amount'])} {r['category']} "
                                f"expense?", danger=True, yes_text="Void"):
            self.ctx.services.expenses.void_expense(self.ctx.user, r["id"], reason)
            self.load(self.table.offset)

    def categories(self):
        dlg = _CategoryManager(self, self.ctx)
        dlg.exec()
        self.on_show()


class _CategoryManager(ListDialog):
    def __init__(self, parent, ctx):
        self.ctx = ctx
        rows = ctx.services.expenses.list_categories(include_inactive=True)
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        super().__init__(parent, "Expense categories", [Col("name", "Category"),
                                                        Col("status", "Status")], rows,
                         subtitle="Double-click a category to rename or deactivate it.")
        table = self.findChild(DataTable)
        self._table = table
        table.activated.connect(self._edit)
        self.layout().insertWidget(2, button("New category", "primary", lambda: self._edit(None)))

    def _edit(self, row):
        fields = [Field("name", "Name", required=True), Field("is_active", "Active", "check")]
        if FormDialog(self, "Expense category", fields, row or {"is_active": True},
                      lambda d: self.ctx.services.expenses.save_category(
                          self.ctx.user, row["id"] if row else None, d)).exec():
            rows = self.ctx.services.expenses.list_categories(include_inactive=True)
            for r in rows:
                r["status"] = "Active" if r["is_active"] else "Inactive"
            self._table.set_rows(rows)
