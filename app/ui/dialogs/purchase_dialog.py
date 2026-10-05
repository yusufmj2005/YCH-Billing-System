from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from app.config.constants import Perm
from app.services.errors import ValidationError
from app.services.purchase_service import (PurchaseLineRequest, PurchaseRequest,
                                           compute_purchase_line)
from app.ui.dialogs.product_picker import ProductPicker
from app.ui.widgets.common import (button, confirm, date_edit, handle_exception, icon_button,
                                   label, pydate, show_error)
from app.ui.widgets.forms import Field, FormDialog
from app.utils.money import ZERO, fmt_money, fmt_qty

SUPPLIER_FIELDS = [
    Field("name", "Supplier name", required=True, max_length=150),
    Field("contact_person", "Contact person", max_length=150),
    Field("phone", "Phone", max_length=20), Field("email", "Email", max_length=150),
    Field("address", "Address", "multiline"), Field("gstin", "GSTIN", max_length=15),
    Field("notes", "Notes", "multiline"),
]


class PurchaseDialog(QDialog):
    COLS = ["Product", "Qty", "Unit cost", "Discount", "Tax %", "Line total", ""]

    def __init__(self, parent, ctx, purchase: dict | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.purchase = purchase
        self.lines: list[dict] = []
        self.setWindowTitle(f"Edit draft {purchase['purchase_no']}" if purchase else "New purchase")
        self.resize(980, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        f = QFormLayout()
        srow = QHBoxLayout()
        self.supplier = QComboBox()
        self._load_suppliers(purchase["supplier_id"] if purchase else None)
        srow.addWidget(self.supplier, 1)
        if ctx.can(Perm.EDIT_SUPPLIERS):
            srow.addWidget(button("New supplier", None, self._new_supplier))
        self.date = date_edit(purchase["purchase_date"] if purchase else date.today())
        self.ref = QLineEdit(purchase["supplier_invoice_no"] if purchase else "")
        self.ref.setPlaceholderText("Supplier's invoice / bill number")
        self.notes = QPlainTextEdit(purchase["notes"] if purchase else "")
        self.notes.setFixedHeight(46)
        self.update_cost = QCheckBox("Update product cost prices from this purchase")
        self.update_cost.setChecked(purchase["update_cost_prices"] if purchase else True)
        f.addRow("Supplier *", srow)
        f.addRow("Purchase date *", self.date)
        f.addRow("Supplier invoice", self.ref)
        f.addRow("Notes", self.notes)
        f.addRow("", self.update_cost)
        lay.addLayout(f)

        arow = QHBoxLayout()
        arow.addWidget(label("Items", "SectionTitle"))
        arow.addStretch(1)
        self.code = QLineEdit()
        self.code.setPlaceholderText("Scan barcode / SKU and press Enter")
        self.code.returnPressed.connect(self._scan)
        arow.addWidget(self.code)
        arow.addWidget(button("Add product…", "primary", self._pick))
        lay.addLayout(arow)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 80), (2, 100), (3, 90), (4, 70), (5, 110), (6, 34)):
            self.table.setColumnWidth(i, w)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self._edited)
        lay.addWidget(self.table, 1)
        lay.addWidget(label("Unit cost excludes tax. Double-click a cell to edit quantity, cost, "
                            "discount or tax %.", "Faint"))
        self.totals = label("", "SectionTitle")
        self.totals.setAlignment(Qt.AlignRight)
        lay.addWidget(self.totals)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(button("Cancel", None, self.reject))
        btns.addWidget(button("Save draft", None, lambda: self._save(False)))
        btns.addWidget(button("Save & complete (add stock)", "success", lambda: self._save(True)))
        lay.addLayout(btns)

        if purchase:
            for it in purchase["items"]:
                self.lines.append({"product_id": it["product_id"], "name": it["product_name"],
                                   "qty": it["quantity"], "cost": it["unit_cost"],
                                   "discount": it["discount_amount"], "tax": it["tax_rate"],
                                   "fraction": True})
        self._refresh()

    def _load_suppliers(self, select_id=None):
        self.supplier.clear()
        self.supplier.addItem("— Select supplier —", None)
        for s in self.ctx.services.partners.list_suppliers(self.ctx.user):
            self.supplier.addItem(s["name"], s["id"])
        self.supplier.setCurrentIndex(max(0, self.supplier.findData(select_id)))

    def _new_supplier(self):
        dlg = FormDialog(self, "New supplier", SUPPLIER_FIELDS,
                         on_submit=lambda d: self.ctx.services.partners.save_supplier(
                             self.ctx.user, None, d))
        if dlg.exec():
            self._load_suppliers(dlg.result_value)

    def _add(self, p: dict):
        for ln in self.lines:
            if ln["product_id"] == p["id"]:
                ln["qty"] += 1
                self._refresh()
                return
        self.lines.append({"product_id": p["id"], "name": p["name"], "qty": Decimal(1),
                           "cost": p["purchase_price"], "discount": ZERO,
                           "tax": p.get("tax_rate") or ZERO,
                           "fraction": p.get("allow_fractional_qty", False)})
        self._refresh()

    def _pick(self):
        dlg = ProductPicker(self, self.ctx)
        if dlg.exec() and dlg.selected:
            self._add(dlg.selected)

    def _scan(self):
        try:
            p = self.ctx.services.catalog.find_by_code(self.ctx.user, self.code.text())
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        if p:
            self._add(p)
            self.code.clear()
        else:
            dlg = ProductPicker(self, self.ctx, self.code.text())
            if dlg.exec() and dlg.selected:
                self._add(dlg.selected)
                self.code.clear()

    _busy = False

    def _refresh(self):
        self._busy = True
        self.table.setRowCount(len(self.lines))
        total = tax_total = ZERO
        for i, ln in enumerate(self.lines):
            try:
                _, _, _, tax, line_total = compute_purchase_line(ln["qty"], ln["cost"],
                                                                 ln["discount"], ln["tax"])
            except ValidationError:
                tax, line_total = ZERO, ZERO
            total += line_total
            tax_total += tax
            vals = [ln["name"], fmt_qty(ln["qty"]), f"{ln['cost']:.2f}", f"{ln['discount']:.2f}",
                    f"{Decimal(ln['tax']).normalize():f}", fmt_money(line_total)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c in (0, 5):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, it)
            self.table.setCellWidget(i, 6, icon_button(
                "✕", lambda _=False, r=i: self._remove(r), "Remove line"))
        self.totals.setText(f"Tax {self.ctx.money(tax_total)}     Total "
                            f"{self.ctx.money(total)}")
        self._busy = False

    def _remove(self, row):
        if 0 <= row < len(self.lines):
            self.lines.pop(row)
            self._refresh()

    def _edited(self, item):
        if self._busy:
            return
        ln = self.lines[item.row()]
        key = {1: "qty", 2: "cost", 3: "discount", 4: "tax"}.get(item.column())
        if not key:
            return
        try:
            val = Decimal(item.text().strip() or "0")
            if val < 0 or (key == "qty" and val <= 0) or (key == "tax" and val > 100):
                raise ValueError
            ln[key] = val
        except Exception:  # noqa: BLE001
            show_error(self, "Enter a valid non-negative number.")
        self._refresh()

    def _save(self, complete: bool):
        if complete and not confirm(self, "Complete this purchase? Stock will be added for every "
                                          "item and the purchase can no longer be edited."):
            return
        req = PurchaseRequest(
            supplier_id=self.supplier.currentData(), purchase_date=pydate(self.date.date()),
            lines=[PurchaseLineRequest(ln["product_id"], ln["qty"], ln["cost"], ln["discount"],
                                       ln["tax"]) for ln in self.lines],
            supplier_invoice_no=self.ref.text(), notes=self.notes.toPlainText(),
            update_cost_prices=self.update_cost.isChecked())
        try:
            res = self.ctx.services.purchases.save_draft(
                self.ctx.user, self.purchase["id"] if self.purchase else None, req,
                complete=complete)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.ctx.toast(f"Purchase {res['purchase_no']} " + ("completed" if complete else "saved"))
        self.accept()
