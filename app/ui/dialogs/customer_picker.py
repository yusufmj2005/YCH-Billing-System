from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.widgets.common import button, handle_exception, label, search_box
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

CUSTOMER_FIELDS = [
    Field("name", "Name", required=True, max_length=150),
    Field("phone", "Phone", max_length=20),
    Field("email", "Email", max_length=150),
    Field("address", "Address", "multiline"),
    Field("gstin", "GSTIN", max_length=15, help="Only for GST-registered business customers"),
    Field("notes", "Notes", "multiline"),
]


class CustomerPicker(QDialog):
    """Search and select a customer (or walk-in) for the current sale."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.selected = None
        self.setWindowTitle("Select customer")
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        top = QHBoxLayout()
        self.search = search_box("Search name, phone or email…", self.refresh)
        top.addWidget(self.search, 1)
        if ctx.can(Perm.EDIT_CUSTOMERS):
            top.addWidget(button("New customer", None, self.new_customer))
        lay.addLayout(top)
        self.table = DataTable([Col("name", "Name"), Col("phone", "Phone"),
                                Col("email", "Email")], stretch="name")
        self.table.activated.connect(self._choose)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("Walk-in (no customer)", None, self._walk_in))
        row.addStretch(1)
        row.addWidget(button("Cancel", None, self.reject))
        row.addWidget(button("Select", "primary", lambda: self._choose(self.table.selected())))
        lay.addLayout(row)
        lay.addWidget(label("Customer details are optional for walk-in sales.", "Faint"))
        self.refresh()
        self.search.setFocus()
        self.search.returnPressed.connect(lambda: self.table.view.setFocus())

    def refresh(self):
        try:
            self.table.set_rows(self.ctx.services.partners.list_customers(
                self.ctx.user, self.search.text(), limit=200))
            if self.table.model.rows:
                self.table.view.selectRow(0)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)

    def _choose(self, row):
        if row:
            self.selected = row
            self.accept()

    def _walk_in(self):
        self.selected = None
        self.accept()

    def new_customer(self):
        dlg = FormDialog(self, "New customer", CUSTOMER_FIELDS,
                         {"name": self.search.text()},
                         on_submit=lambda d: self.ctx.services.partners.save_customer(
                             self.ctx.user, None, d))
        if dlg.exec():
            rows = self.ctx.services.partners.list_customers(self.ctx.user)
            self.selected = next((r for r in rows if r["id"] == dlg.result_value), None)
            self.accept()
