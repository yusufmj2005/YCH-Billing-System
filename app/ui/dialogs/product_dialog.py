from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QVBoxLayout)

from app.config.constants import Perm
from app.ui.widgets.common import button, handle_exception, label
from app.ui.widgets.forms import decimal_edit


class ProductDialog(QDialog):
    def __init__(self, parent, ctx, product: dict | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self.saved_id = None
        self.setWindowTitle("Edit product" if product else "New product")
        self.setMinimumWidth(760)
        p = product or {}
        settings = ctx.settings
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)

        basic = QGroupBox("Product")
        f1 = QFormLayout(basic)
        self.name = QLineEdit(p.get("name", ""))
        self.name.setMaxLength(200)
        self.category = QComboBox()
        self.category.addItem("— None —", None)
        for c in ctx.services.catalog.list_categories(include_inactive=bool(product)):
            self.category.addItem(c["name"], c["id"])
        self.category.setCurrentIndex(max(0, self.category.findData(p.get("category_id"))))
        self.brand = QLineEdit(p.get("brand", ""))
        self.supplier = QComboBox()
        self.supplier.addItem("— None —", None)
        if ctx.can(Perm.VIEW_SUPPLIERS) or ctx.can(Perm.EDIT_PRODUCTS):
            for s in ctx.services.partners.list_suppliers(ctx.user, include_inactive=bool(product)):
                self.supplier.addItem(s["name"], s["id"])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(p.get("supplier_id"))))
        self.description = QPlainTextEdit(p.get("description", ""))
        self.description.setFixedHeight(60)
        self.active = QCheckBox("Active (available for sale)")
        self.active.setChecked(p.get("is_active", True))
        self.image_path = p.get("image_path") or ""
        img_row = QHBoxLayout()
        self.image_lbl = QLabel()
        self.image_lbl.setFixedSize(64, 64)
        self.image_lbl.setAlignment(Qt.AlignCenter)
        self.image_lbl.setStyleSheet("border: 1px solid #E2E5EA; border-radius: 6px;")
        img_row.addWidget(self.image_lbl)
        img_row.addWidget(button("Choose image…", None, self._pick_image))
        img_row.addWidget(button("Remove", "ghost", self._clear_image))
        img_row.addStretch(1)
        self._show_image()
        f1.addRow("Name *", self.name)
        f1.addRow("Category", self.category)
        f1.addRow("Brand", self.brand)
        f1.addRow("Supplier", self.supplier)
        f1.addRow("Description", self.description)
        f1.addRow("Image", img_row)
        f1.addRow("", self.active)
        grid.addWidget(basic, 0, 0, 2, 1)

        codes = QGroupBox("Codes")
        f2 = QFormLayout(codes)
        self.sku = QLineEdit(p.get("sku", ""))
        self.sku.setMaxLength(64)
        brow = QHBoxLayout()
        self.barcode = QLineEdit(p.get("barcode", ""))
        self.barcode.setMaxLength(64)
        self.barcode.setPlaceholderText("Scan, type, or generate")
        brow.addWidget(self.barcode, 1)
        gen = button("Generate", None, self._generate)
        gen.setEnabled(ctx.can(Perm.MANAGE_BARCODES) or ctx.can(Perm.EDIT_PRODUCTS))
        brow.addWidget(gen)
        self.hsn = QLineEdit(p.get("hsn_code", ""))
        self.hsn.setMaxLength(16)
        f2.addRow("SKU", self.sku)
        f2.addRow("Barcode", brow)
        f2.addRow("HSN / SAC", self.hsn)
        grid.addWidget(codes, 0, 1)

        price = QGroupBox("Pricing & tax")
        f3 = QFormLayout(price)
        self.purchase_price = decimal_edit(p.get("purchase_price"))
        self.selling_price = decimal_edit(p.get("selling_price"))
        self.tax = QComboBox()
        self.tax.addItem("No tax", None)
        for t in ctx.services.catalog.list_tax_rates(include_inactive=bool(product)):
            self.tax.addItem(f"{t['name']} ({t['rate'].normalize():f}%)", t["id"])
        self.tax.setCurrentIndex(max(0, self.tax.findData(p.get("tax_rate_id"))))
        self.incl = QCheckBox("Selling price includes tax")
        self.incl.setChecked(p.get("price_includes_tax",
                                   bool(settings.get("default_price_includes_tax", True))))
        f3.addRow("Cost price", self.purchase_price)
        f3.addRow("Selling price *", self.selling_price)
        f3.addRow("Tax rate", self.tax)
        f3.addRow("", self.incl)
        if self.tax.count() == 1:
            f3.addRow("", label("No tax rates configured yet (Settings › Tax).", "Faint"))
        grid.addWidget(price, 1, 1)

        stock = QGroupBox("Stock")
        f4 = QFormLayout(stock)
        self.unit = QComboBox()
        self.unit.setEditable(True)
        for u in settings.get("units") or []:
            self.unit.addItem(u)
        self.unit.setCurrentText(p.get("unit") or (settings.get("units") or ["pcs"])[0])
        self.min_stock = decimal_edit(p.get("min_stock_level"), "Uses global threshold if blank")
        self.fraction = QCheckBox("Allow fractional quantities (e.g. metres, grams)")
        self.fraction.setChecked(p.get("allow_fractional_qty", False))
        f4.addRow("Unit *", self.unit)
        f4.addRow("Minimum stock level", self.min_stock)
        f4.addRow("", self.fraction)
        if product is None:
            self.opening = decimal_edit(None, "0")
            self.opening.setEnabled(ctx.can(Perm.ADJUST_INVENTORY))
            f4.addRow("Opening stock", self.opening)
            f4.addRow("", label("Recorded as a stock adjustment. Later stock changes come from "
                                "purchases, sales, returns and adjustments.", "Faint", wrap=True))
        else:
            f4.addRow("Current stock", label(f"{p['current_stock'].normalize():f} {p['unit']}"
                                             "  (change via purchases or stock adjustment)",
                                             "Muted"))
        grid.addWidget(stock, 2, 0, 1, 2)
        root.addLayout(grid)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.name.setFocus()

    def _show_image(self):
        f = self.ctx.services.catalog.image_file(self.image_path)
        pm = QPixmap(str(f)) if f else QPixmap()
        if pm.isNull():
            self.image_lbl.setPixmap(QPixmap())
            self.image_lbl.setText("No image")
        else:
            self.image_lbl.setPixmap(pm.scaled(60, 60, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose product image", "",
                                              "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            self.image_path = self.ctx.services.catalog.store_product_image(self.ctx.user, path)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self._show_image()

    def _clear_image(self):
        self.image_path = ""
        self._show_image()

    def _generate(self):
        try:
            self.barcode.setText(self.ctx.services.catalog.generate_barcode(self.ctx.user))
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)

    def data(self) -> dict:
        d = {
            "name": self.name.text(), "category_id": self.category.currentData(),
            "brand": self.brand.text(), "supplier_id": self.supplier.currentData(),
            "description": self.description.toPlainText(), "sku": self.sku.text(),
            "barcode": self.barcode.text(), "hsn_code": self.hsn.text(),
            "purchase_price": self.purchase_price.text() or "0",
            "selling_price": self.selling_price.text(), "tax_rate_id": self.tax.currentData(),
            "price_includes_tax": self.incl.isChecked(), "unit": self.unit.currentText(),
            "min_stock_level": self.min_stock.text(),
            "allow_fractional_qty": self.fraction.isChecked(),
            "image_path": self.image_path,
        }
        if self.product is None:
            d["opening_stock"] = self.opening.text()
        return d

    def _save(self):
        svc = self.ctx.services.catalog
        try:
            if self.product is None:
                self.saved_id = svc.create_product(self.ctx.user, self.data())
                if not self.active.isChecked():
                    svc.set_product_active(self.ctx.user, self.saved_id, False)
            else:
                svc.update_product(self.ctx.user, self.product["id"], self.data())
                if self.active.isChecked() != self.product["is_active"]:
                    svc.set_product_active(self.ctx.user, self.product["id"],
                                           self.active.isChecked())
                self.saved_id = self.product["id"]
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.accept()
