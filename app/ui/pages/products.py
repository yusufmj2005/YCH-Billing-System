from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout

from app.config.constants import MOVEMENT_TYPE_LABELS, Perm
from app.reports.base import Col
from app.ui.dialogs.labels_dialog import LabelsDialog
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.dialogs.simple_list_dialog import ListDialog
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import button, confirm, label, search_box, show_info, ui_action
from app.ui.widgets.table import DataTable

PAGE = 200


class ProductsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Search name, SKU, barcode or brand…", lambda: self.load(0))
        self.category = QComboBox()
        self.status = QComboBox()
        for text, key in (("Active", "active"), ("Inactive", "inactive"), ("All", "all")):
            self.status.addItem(text, key)
        self.low = QCheckBox("Low stock only")
        for w in (self.category, self.status):
            w.currentIndexChanged.connect(lambda: self.load(0))
        self.low.toggled.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.category)
        bar.addWidget(self.status)
        bar.addWidget(self.low)
        bar.addStretch(1)
        if ctx.can(Perm.EDIT_PRODUCTS):
            bar.addWidget(button("New product", "primary", self.new_product))
        self.root.addLayout(bar)

        self.table = DataTable([
            Col("name", "Product"), Col("sku", "SKU"), Col("barcode", "Barcode"),
            Col("category", "Category"), Col("brand", "Brand"),
            Col("purchase_price", "Cost", "money"), Col("selling_price", "Price", "money"),
            Col("tax_name", "Tax"), Col("current_stock", "Stock", "qty"), Col("unit", "Unit"),
            Col("status", "Status")], page_size=PAGE, stretch="name")
        self.table.set_row_color(self._color)
        self.table.pageRequested.connect(self.load)
        self.table.activated.connect(self.edit_product)
        self.root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.count = label("", "Muted")
        actions.addWidget(self.count)
        actions.addStretch(1)
        if ctx.can(Perm.EDIT_PRODUCTS):
            actions.addWidget(button("Edit", None, lambda: self.edit_product(self.table.selected())))
            actions.addWidget(button("Activate / Deactivate", None, self.toggle_active))
        if ctx.can(Perm.VIEW_INVENTORY):
            actions.addWidget(button("Stock history", None, self.history))
        if ctx.can(Perm.MANAGE_BARCODES):
            actions.addWidget(button("Print labels", None, self.labels))
        self.root.addLayout(actions)
        self._threshold = None

    def _color(self, r):
        if not r["is_active"]:
            return C["faint"]
        level = r["min_stock_level"] if r["min_stock_level"] is not None else self._threshold
        if level is not None and r["current_stock"] <= level:
            return C["warning"]
        return None

    def on_show(self):
        self.ctx.reload_settings()
        from decimal import Decimal
        self._threshold = Decimal(str(self.ctx.settings.get("low_stock_threshold") or "0"))
        cur = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("All categories", None)
        for c in self.ctx.services.catalog.list_categories(include_inactive=True):
            self.category.addItem(c["name"], c["id"])
        self.category.setCurrentIndex(max(0, self.category.findData(cur)))
        self.category.blockSignals(False)
        self.load(0)

    @ui_action
    def load(self, offset: int = 0):
        rows, total = self.ctx.services.catalog.list_products(
            self.ctx.user, search=self.search.text(), category_id=self.category.currentData(),
            status=self.status.currentData(), low_stock_only=self.low.isChecked(), limit=PAGE,
            offset=offset)
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.table.set_rows(rows, total, offset)
        self.count.setText(f"{total} product(s)")

    @ui_action
    def new_product(self):
        if ProductDialog(self, self.ctx).exec():
            self.ctx.toast("Product created")
            self.load(0)

    @ui_action
    def edit_product(self, row):
        if not row or not self.ctx.can(Perm.EDIT_PRODUCTS):
            return
        product = self.ctx.services.catalog.get_product(self.ctx.user, row["id"])
        if ProductDialog(self, self.ctx, product).exec():
            self.ctx.toast("Product saved")
            self.load(self.table.offset)

    @ui_action
    def toggle_active(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a product first.")
            return
        new = not r["is_active"]
        verb = "Activate" if new else "Deactivate"
        if confirm(self, f"{verb} “{r['name']}”?" + (
                "" if new else "\n\nDeactivated products are hidden from POS. Their sales "
                               "history is kept."), yes_text=verb):
            self.ctx.services.catalog.set_product_active(self.ctx.user, r["id"], new)
            self.load(self.table.offset)

    @ui_action
    def history(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a product first.")
            return
        rows = self.ctx.services.catalog.product_history(self.ctx.user, r["id"])
        for x in rows:
            x["type"] = MOVEMENT_TYPE_LABELS.get(x["movement_type"], x["movement_type"])
        ListDialog(self, f"Stock history — {r['name']}", [
            Col("created_at", "Date", "datetime"), Col("type", "Movement"),
            Col("quantity", "Change", "qty"), Col("balance_after", "Balance", "qty"),
            Col("reference_no", "Reference"), Col("reason", "Reason"), Col("user", "User")],
            rows, subtitle=f"Current stock: {r['current_stock'].normalize():f} {r['unit']}",
            stretch="reason").exec()

    @ui_action
    def labels(self):
        r = self.table.selected()
        if not r:
            show_info(self, "Select a product first.")
            return
        if not r["barcode"]:
            show_info(self, "This product has no barcode yet. Edit it and enter or generate a "
                            "barcode first.")
            return
        LabelsDialog(self, self.ctx, r).exec()
