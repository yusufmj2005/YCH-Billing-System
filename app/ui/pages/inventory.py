from __future__ import annotations

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLineEdit, QRadioButton, QTabWidget, QVBoxLayout,
                               QWidget)

from app.config.constants import MOVEMENT_TYPE_LABELS, Perm
from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import (DateRangeBar, StatCard, button, handle_exception, label,
                                   search_box, show_info, ui_action)
from app.ui.widgets.forms import decimal_edit
from app.ui.widgets.table import DataTable
from app.utils.money import fmt_qty

PAGE = 200


class AdjustStockDialog(QDialog):
    def __init__(self, parent, ctx, product: dict):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self.setWindowTitle("Adjust stock")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label(product["name"], "SectionTitle"))
        lay.addWidget(label(f"Current stock: {fmt_qty(product['current_stock'])} "
                            f"{product['unit']}", "Muted"))
        row = QHBoxLayout()
        self.r_in = QRadioButton("Add stock")
        self.r_out = QRadioButton("Remove stock")
        self.r_set = QRadioButton("Set to counted quantity")
        g = QButtonGroup(self)
        for r in (self.r_in, self.r_out, self.r_set):
            g.addButton(r)
            row.addWidget(r)
        self.r_in.setChecked(True)
        lay.addLayout(row)
        f = QFormLayout()
        self.qty = decimal_edit(None, "0")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Required, e.g. damaged, stock count, found")
        f.addRow("Quantity *", self.qty)
        f.addRow("Reason *", self.reason)
        lay.addLayout(f)
        lay.addWidget(label("Every adjustment is recorded in the stock ledger and audit log.",
                            "Faint"))
        b = QHBoxLayout()
        b.addStretch(1)
        b.addWidget(button("Cancel", None, self.reject))
        b.addWidget(button("Save adjustment", "primary", self._save))
        lay.addLayout(b)

    def _save(self):
        direction = "IN" if self.r_in.isChecked() else "OUT" if self.r_out.isChecked() else "SET"
        try:
            self.ctx.services.inventory.adjust_stock(self.ctx.user, self.product["id"],
                                                     direction=direction,
                                                     quantity=self.qty.text(),
                                                     reason=self.reason.text())
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.accept()


class InventoryPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        cards = QHBoxLayout()
        self.c_value = StatCard("Inventory value (at cost)")
        self.c_products = StatCard("Active products")
        self.c_low = StatCard("Low-stock products")
        for c in (self.c_value, self.c_products, self.c_low):
            cards.addWidget(c)
        self.root.addLayout(cards)

        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)

        # ---- stock levels
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        self.search = search_box("Search product, SKU or barcode…", self.load_levels)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self.load_levels)
        self.low = QCheckBox("Low stock only")
        self.low.toggled.connect(self.load_levels)
        bar.addWidget(self.search)
        bar.addWidget(self.category)
        bar.addWidget(self.low)
        bar.addStretch(1)
        if ctx.can(Perm.ADJUST_INVENTORY):
            bar.addWidget(button("Adjust stock…", "primary", self.adjust))
        l1.addLayout(bar)
        self.levels = DataTable([
            Col("name", "Product"), Col("sku", "SKU"), Col("category", "Category"),
            Col("current_stock", "In stock", "qty"), Col("unit", "Unit"),
            Col("min_stock", "Minimum", "qty"), Col("purchase_price", "Cost", "money"),
            Col("stock_value", "Stock value", "money"), Col("state", "Status")], stretch="name")
        self.levels.set_row_color(lambda r: C["warning"] if r["is_low"] else None)
        self.levels.activated.connect(lambda r: self.adjust())
        l1.addWidget(self.levels, 1)
        tabs.addTab(w1, "Stock levels")

        # ---- movements
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(0, 8, 0, 0)
        bar2 = QHBoxLayout()
        self.m_search = search_box("Product, SKU or reference…", lambda: self.load_moves(0))
        self.m_range = DateRangeBar("this_month")
        self.m_range.changed.connect(lambda: self.load_moves(0))
        self.m_type = QComboBox()
        self.m_type.addItem("All movement types", None)
        for k, v in MOVEMENT_TYPE_LABELS.items():
            self.m_type.addItem(v, k)
        self.m_type.currentIndexChanged.connect(lambda: self.load_moves(0))
        bar2.addWidget(self.m_search)
        bar2.addWidget(self.m_range)
        bar2.addWidget(self.m_type)
        bar2.addStretch(1)
        l2.addLayout(bar2)
        self.moves = DataTable([
            Col("created_at", "Date", "datetime"), Col("product", "Product"),
            Col("type", "Movement"), Col("quantity", "Change", "qty"),
            Col("balance_after", "Balance", "qty"), Col("reference_no", "Reference"),
            Col("reason", "Reason"), Col("user", "User")], page_size=PAGE, stretch="reason")
        self.moves.set_row_color(lambda r: C["danger"] if r["quantity"] < 0 else C["success"])
        self.moves.pageRequested.connect(self.load_moves)
        l2.addWidget(self.moves, 1)
        tabs.addTab(w2, "Stock movements")
        self.tabs = tabs
        tabs.currentChanged.connect(lambda i: self.load_moves(0) if i == 1 else None)

    def on_show(self):
        cur = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for c in self.ctx.services.catalog.list_categories(include_inactive=True):
            self.category.addItem(c["name"], c["id"])
        self.category.setCurrentIndex(max(0, self.category.findData(cur)))
        self.category.blockSignals(False)
        self.load_levels()
        if self.tabs.currentIndex() == 1:
            self.load_moves(0)

    @ui_action
    def load_levels(self):
        s = self.ctx.services.inventory.summary()
        self.c_value.set(self.ctx.money(s["inventory_value"]), "Current stock × cost price")
        self.c_products.set(str(s["active_products"]))
        self.c_low.set(str(s["low_stock"]), "At or below minimum level")
        rows = self.ctx.services.inventory.stock_levels(
            self.ctx.user, search=self.search.text(), category_id=self.category.currentData(),
            low_only=self.low.isChecked())
        for r in rows:
            r["state"] = "Low" if r["is_low"] else "OK"
        self.levels.set_rows(rows)

    @ui_action
    def load_moves(self, offset: int = 0):
        a, b = self.m_range.range()
        rows, total = self.ctx.services.inventory.movements(
            self.ctx.user, movement_type=self.m_type.currentData(), date_from=a, date_to=b,
            search=self.m_search.text(), limit=PAGE, offset=offset)
        for r in rows:
            r["type"] = MOVEMENT_TYPE_LABELS.get(r["movement_type"], r["movement_type"])
        self.moves.set_rows(rows, total, offset)

    def adjust(self):
        if not self.ctx.can(Perm.ADJUST_INVENTORY):
            return
        r = self.levels.selected()
        if not r:
            show_info(self, "Select a product in the stock list first.")
            return
        if AdjustStockDialog(self, self.ctx, r).exec():
            self.ctx.toast("Stock adjusted")
            self.load_levels()
