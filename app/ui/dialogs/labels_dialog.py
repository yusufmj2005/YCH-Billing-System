from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QSpinBox, QVBoxLayout)

from app.printing.label_pdf import LABEL_LAYOUTS, build_labels_pdf
from app.printing.printer import print_pdf
from app.ui.widgets.common import button, handle_exception, label, show_error


class LabelsDialog(QDialog):
    """Generate a barcode label PDF for one product and print / open it."""

    def __init__(self, parent, ctx, product: dict):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self.setWindowTitle("Print barcode labels")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label(product["name"], "SectionTitle"))
        lay.addWidget(label(f"Barcode: {product['barcode']}", "Muted"))
        f = QFormLayout()
        self.layout_box = QComboBox()
        for name in LABEL_LAYOUTS:
            self.layout_box.addItem(name)
        self.copies = QSpinBox()
        self.copies.setRange(1, 1000)
        self.copies.setValue(1)
        self.price = QCheckBox("Show price")
        self.price.setChecked(True)
        self.name = QCheckBox("Show product name")
        self.name.setChecked(True)
        f.addRow("Label layout", self.layout_box)
        f.addRow("Number of labels", self.copies)
        f.addRow("", self.price)
        f.addRow("", self.name)
        lay.addLayout(f)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", None, self.reject))
        row.addWidget(button("Open PDF", None, lambda: self._make(False)))
        row.addWidget(button("Print", "primary", lambda: self._make(True)))
        lay.addLayout(row)

    def _make(self, do_print: bool):
        if not self.product.get("barcode"):
            show_error(self, "This product has no barcode. Edit the product to add one.")
            return
        try:
            out = self.ctx.export_path("labels", f"labels-{self.product['id']}.pdf")
            build_labels_pdf([{"name": self.product["name"], "barcode": self.product["barcode"],
                               "price": self.product["selling_price"],
                               "copies": self.copies.value()}], out,
                             self.layout_box.currentText(), self.ctx.settings,
                             show_price=self.price.isChecked(), show_name=self.name.isChecked())
            if do_print:
                print_pdf(self, out, title="Print labels")
            else:
                self.ctx.open_file(out)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
