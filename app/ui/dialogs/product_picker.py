from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from app.reports.base import Col
from app.ui.widgets.common import button, handle_exception, search_box
from app.ui.widgets.table import DataTable


class ProductPicker(QDialog):
    def __init__(self, parent, ctx, initial: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.selected = None
        self.setWindowTitle("Select product")
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        self.search = search_box("Search name, SKU or scan barcode…", self.refresh)
        self.search.setText(initial)
        lay.addWidget(self.search)
        self.table = DataTable([Col("name", "Product"), Col("sku", "SKU"),
                                Col("purchase_price", "Cost", "money"),
                                Col("current_stock", "Stock", "qty"), Col("unit", "Unit")],
                               stretch="name")
        self.table.activated.connect(self._choose)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", None, self.reject))
        row.addWidget(button("Select", "primary", lambda: self._choose(self.table.selected())))
        lay.addLayout(row)
        self.search.returnPressed.connect(self._enter)
        self.refresh()

    def refresh(self):
        try:
            rows = self.ctx.services.catalog.search_for_sale(self.ctx.user, self.search.text(), 200)
            self.table.set_rows(rows)
            if rows:
                self.table.view.selectRow(0)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)

    def _enter(self):
        p = self.ctx.services.catalog.find_by_code(self.ctx.user, self.search.text())
        if p:
            self._choose(p)
        else:
            self.table.view.setFocus()

    def _choose(self, row):
        if row:
            self.selected = row
            self.accept()
