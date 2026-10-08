"""POS / Billing screen — optimised for keyboard and barcode-scanner use.

Shortcuts: F2 search, Enter add, +/- quantity, Del remove line, F4 customer,
F6 item discount, F7 bill discount, F12 checkout, Esc clear search.
A USB scanner acting as a keyboard types the code followed by Enter, which
triggers an exact barcode/SKU lookup and adds the item to the cart.
"""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLineEdit, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.config.constants import TAX_MODE_LABELS, Perm, TaxMode
from app.reports.base import Col
from app.services.errors import ValidationError
from app.services.pricing import CartLineInput, compute_cart
from app.services.sales_service import SaleLineRequest, SaleRequest
from app.ui.dialogs.checkout_dialog import CheckoutDialog, DiscountDialog
from app.ui.dialogs.customer_picker import CustomerPicker
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import button, confirm, icon_button, label, show_error, ui_action
from app.ui.widgets.table import DataTable
from app.utils.money import ZERO, fmt_money, fmt_qty
from app.validators import common as v


class PosPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.cart: list[dict] = []  # {product, qty, disc_amount, disc_percent}
        self.customer: dict | None = None
        self.bill_disc_amount = ZERO
        self.bill_disc_percent: Decimal | None = None
        self.result = None

        # ---- search bar ------------------------------------------------------------
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("SearchBig")
        self.search.setPlaceholderText("Scan barcode or search by name / SKU   (F2)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search_enter)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.installEventFilter(self)
        top.addWidget(self.search, 1)
        self.root.addLayout(top)
        self._search_timer = QTimer(self, singleShot=True, interval=200, timeout=self._do_search)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # ---- product results -------------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        ll.setSpacing(6)
        ll.addWidget(label("Products", "SectionTitle"))
        self.results = DataTable([Col("name", "Product"), Col("sku", "SKU"),
                                  Col("selling_price", "Price", "money"),
                                  Col("stock_txt", "In stock")], stretch="name")
        self.results.activated.connect(lambda p: self.add_product(p))
        self.results.view.installEventFilter(self)
        self.results.set_row_color(lambda r: C["danger"] if r["current_stock"] <= 0 else None)
        ll.addWidget(self.results, 1)
        ll.addWidget(label("Enter or double-click adds the selected product.", "Faint"))
        split.addWidget(left)

        # ---- cart ------------------------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.setSpacing(8)
        cust_row = QHBoxLayout()
        cust_row.addWidget(label("Cart", "SectionTitle"))
        cust_row.addStretch(1)
        self.customer_btn = button("Customer: Walk-in  (F4)", None, self.pick_customer)
        cust_row.addWidget(self.customer_btn)
        rl.addLayout(cust_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Product", "Qty", "Price", "Discount", "Total", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 70), (2, 90), (3, 90), (4, 100), (5, 34)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.table.setColumnWidth(i, w)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemChanged.connect(self._qty_edited)
        self.table.installEventFilter(self)
        rl.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.btn_item_disc = button("Item discount (F6)", None, self.item_discount)
        self.btn_bill_disc = button("Bill discount (F7)", None, self.bill_discount)
        actions.addWidget(self.btn_item_disc)
        actions.addWidget(self.btn_bill_disc)
        actions.addStretch(1)
        actions.addWidget(button("Remove (Del)", None, self.remove_line))
        actions.addWidget(button("Clear cart", "danger", self.clear_cart))
        rl.addLayout(actions)
        if not ctx.can(Perm.APPLY_DISCOUNT):
            self.btn_item_disc.setEnabled(False)
            self.btn_bill_disc.setEnabled(False)
            self.btn_item_disc.setToolTip("You do not have permission to apply discounts.")
            self.btn_bill_disc.setToolTip("You do not have permission to apply discounts.")

        panel = QFrame()
        panel.setObjectName("TotalsPanel")
        pg = QGridLayout(panel)
        pg.setContentsMargins(16, 12, 16, 12)
        pg.setVerticalSpacing(4)
        self.tax_mode = QComboBox()
        for k, text in TAX_MODE_LABELS.items():
            self.tax_mode.addItem(text, k)
        self.tax_mode.currentIndexChanged.connect(self.recalc)
        self.lbl = {}
        rows = [("gross", "Subtotal"), ("discount", "Discount"), ("taxable", "Taxable value"),
                ("tax", "Tax"), ("round", "Round off")]
        for i, (key, text) in enumerate(rows):
            a = label(text, "Muted")
            b = label("0.00")
            b.setAlignment(Qt.AlignRight)
            pg.addWidget(a, i, 0)
            pg.addWidget(b, i, 1)
            self.lbl[key] = (a, b)
        r = len(rows)
        pg.addWidget(label("Tax type", "Muted"), r, 0)
        pg.addWidget(self.tax_mode, r, 1)
        total_lbl = label("Grand total", "SectionTitle")
        self.grand = label("0.00", "BigTotal")
        self.grand.setAlignment(Qt.AlignRight)
        pg.addWidget(total_lbl, r + 1, 0)
        pg.addWidget(self.grand, r + 1, 1)
        self.checkout_btn = button("Checkout  (F12)", "success", self.checkout)
        self.checkout_btn.setObjectName("Checkout")
        pg.addWidget(self.checkout_btn, r + 2, 0, 1, 2)
        rl.addWidget(panel)
        self.error_lbl = label("", "ErrorText", wrap=True)
        rl.addWidget(self.error_lbl)

        split.addWidget(right)
        split.setSizes([560, 620])
        self.root.addWidget(split, 1)

        for key, fn in (("F2", self.focus_search), ("F4", self.pick_customer),
                        ("F6", self.item_discount), ("F7", self.bill_discount),
                        ("F12", self.checkout), ("Delete", self.remove_line)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ---- lifecycle -------------------------------------------------------------------
    def on_show(self) -> None:
        self.ctx.reload_settings()
        if not self.cart:
            idx = self.tax_mode.findData(self.ctx.settings.get("default_tax_mode") or TaxMode.INTRA)
            self.tax_mode.setCurrentIndex(max(0, idx))
        self._do_search()
        self.recalc()
        self.focus_search()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if obj is self.search:
                if key == Qt.Key_Down:
                    self.results.view.setFocus()
                    if self.results.view.model().rowCount():
                        self.results.view.selectRow(0)
                    return True
                if key == Qt.Key_Escape:
                    self.search.clear()
                    return True
            elif obj is self.results.view and key in (Qt.Key_Return, Qt.Key_Enter):
                p = self.results.selected()
                if p:
                    self.add_product(p)
                return True
            elif obj is self.table and self.table.state() != QAbstractItemView.EditingState:
                if key in (Qt.Key_Plus, Qt.Key_Equal):
                    self.change_qty(+1)
                    return True
                if key == Qt.Key_Minus:
                    self.change_qty(-1)
                    return True
        return super().eventFilter(obj, event)

    # ---- searching ------------------------------------------------------------------
    @ui_action
    def _do_search(self) -> None:
        rows = self.ctx.services.catalog.search_for_sale(self.ctx.user, self.search.text())
        for r in rows:
            r["stock_txt"] = f"{fmt_qty(r['current_stock'])} {r['unit']}"
        self.results.set_rows(rows)

    @ui_action
    def _search_enter(self) -> None:
        code = self.search.text().strip()
        if not code:
            return
        self._search_timer.stop()
        product = self.ctx.services.catalog.find_by_code(self.ctx.user, code)
        if product is None:
            rows = self.ctx.services.catalog.search_for_sale(self.ctx.user, code)
            if len(rows) == 1:
                product = rows[0]
            else:
                self._do_search()
                if not rows:
                    self.error_lbl.setText(f"No product found for “{code}”.")
                    self.search.selectAll()
                    return
                self.results.view.setFocus()
                self.results.view.selectRow(0)
                return
        self.add_product(product)
        self.search.clear()
        self.search.setFocus()

    # ---- cart operations ---------------------------------------------------------------
    def _allow_negative(self) -> bool:
        return bool(self.ctx.settings.get("allow_negative_stock"))

    def _qty_in_cart(self, product_id: int) -> Decimal:
        return sum((ln["qty"] for ln in self.cart if ln["product"]["id"] == product_id), ZERO)

    def add_product(self, product: dict, qty: Decimal = Decimal(1)) -> None:
        self.error_lbl.clear()
        if not self._allow_negative() and \
                self._qty_in_cart(product["id"]) + qty > product["current_stock"]:
            self.error_lbl.setText(f"Insufficient stock for “{product['name']}” "
                                   f"(available: {fmt_qty(product['current_stock'])}).")
            return
        for i, ln in enumerate(self.cart):
            if ln["product"]["id"] == product["id"] and not ln["disc_amount"] \
                    and ln["disc_percent"] is None:
                ln["qty"] += qty
                self.refresh_cart(select=i)
                return
        self.cart.append({"product": product, "qty": qty, "disc_amount": ZERO,
                          "disc_percent": None})
        self.refresh_cart(select=len(self.cart) - 1)

    def _selected_index(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else (len(self.cart) - 1 if self.cart else None)

    def change_qty(self, delta: int) -> None:
        i = self._selected_index()
        if i is None:
            return
        ln = self.cart[i]
        new = ln["qty"] + delta
        if new <= 0:
            self.remove_line()
            return
        if delta > 0 and not self._allow_negative() and \
                self._qty_in_cart(ln["product"]["id"]) + delta > ln["product"]["current_stock"]:
            self.error_lbl.setText("Insufficient stock.")
            return
        ln["qty"] = new
        self.refresh_cart(select=i)

    def remove_line(self) -> None:
        if self.table.state() == QAbstractItemView.EditingState:
            return
        i = self._selected_index()
        if i is not None and 0 <= i < len(self.cart):
            self.cart.pop(i)
            self.refresh_cart(select=min(i, len(self.cart) - 1))

    def clear_cart(self) -> None:
        if self.cart and not confirm(self, "Remove all items from the cart?"):
            return
        self.reset_sale()

    def reset_sale(self) -> None:
        self.cart.clear()
        self.customer = None
        self.bill_disc_amount, self.bill_disc_percent = ZERO, None
        self.customer_btn.setText("Customer: Walk-in  (F4)")
        idx = self.tax_mode.findData(self.ctx.settings.get("default_tax_mode") or TaxMode.INTRA)
        self.tax_mode.setCurrentIndex(max(0, idx))
        self.error_lbl.clear()
        self.refresh_cart()
        self._do_search()
        self.focus_search()

    def _qty_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 1 or self._refreshing:
            return
        i = item.row()
        ln = self.cart[i]
        try:
            q = v.quantity(item.text(), allow_fraction=ln["product"]["allow_fractional_qty"])
            others = self._qty_in_cart(ln["product"]["id"]) - ln["qty"]
            if not self._allow_negative() and others + q > ln["product"]["current_stock"]:
                raise ValidationError(f"Insufficient stock (available: "
                                      f"{fmt_qty(ln['product']['current_stock'])}).")
            ln["qty"] = q
            self.error_lbl.clear()
        except ValidationError as exc:
            self.error_lbl.setText(str(exc))
        self.refresh_cart(select=i)

    _refreshing = False

    def refresh_cart(self, select: int | None = None) -> None:
        self._refreshing = True
        self.table.setRowCount(len(self.cart))
        for i, ln in enumerate(self.cart):
            p = ln["product"]
            name = QTableWidgetItem(p["name"])
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            name.setToolTip(f"SKU {p['sku']}" if p["sku"] else p["name"])
            qty = QTableWidgetItem(fmt_qty(ln["qty"]))
            qty.setTextAlignment(Qt.AlignCenter)
            price = QTableWidgetItem(fmt_money(p["selling_price"]))
            disc_txt = ""
            if ln["disc_percent"] is not None:
                disc_txt = f"{fmt_qty(ln['disc_percent'])}%"
            elif ln["disc_amount"]:
                disc_txt = fmt_money(ln["disc_amount"])
            disc = QTableWidgetItem(disc_txt)
            total = QTableWidgetItem("")
            for it in (price, disc, total):
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, qty)
            self.table.setItem(i, 2, price)
            self.table.setItem(i, 3, disc)
            self.table.setItem(i, 4, total)
            rm = icon_button("✕", lambda _=False, row=i: self._remove_row(row), "Remove line")
            self.table.setCellWidget(i, 5, rm)
        self._refreshing = False
        if select is not None and 0 <= select < len(self.cart):
            self.table.selectRow(select)
        self.recalc()

    def _remove_row(self, row: int) -> None:
        if 0 <= row < len(self.cart):
            self.cart.pop(row)
            self.refresh_cart(select=min(row, len(self.cart) - 1))

    def _inputs(self) -> list[CartLineInput]:
        return [CartLineInput(
            product_id=ln["product"]["id"], name=ln["product"]["name"],
            unit_price=ln["product"]["selling_price"], quantity=ln["qty"],
            tax_rate=ln["product"]["tax_rate"] or ZERO,
            price_includes_tax=ln["product"]["price_includes_tax"],
            discount_amount=ln["disc_amount"], discount_percent=ln["disc_percent"])
            for ln in self.cart]

    def compute(self):
        return compute_cart(self._inputs(), bill_discount_amount=self.bill_disc_amount,
                            bill_discount_percent=self.bill_disc_percent,
                            tax_mode=self.tax_mode.currentData() or TaxMode.INTRA,
                            round_off=bool(self.ctx.settings.get("round_off_total")))

    def recalc(self) -> None:
        try:
            res = self.compute()
        except ValidationError as exc:
            self.error_lbl.setText(str(exc))
            self.checkout_btn.setEnabled(False)
            return
        self.result = res
        self._refreshing = True
        for i, lr in enumerate(res.lines):
            it = self.table.item(i, 4)
            if it:
                it.setText(fmt_money(lr.total))
        self._refreshing = False
        m = self.ctx.money
        self.lbl["gross"][1].setText(m(res.gross_total))
        disc = res.total_discount
        self.lbl["discount"][1].setText(("-" + m(disc)) if disc else m(0))
        self.lbl["taxable"][1].setText(m(res.taxable_total))
        if res.igst_total:
            self.lbl["tax"][0].setText("IGST")
        elif res.tax_total:
            self.lbl["tax"][0].setText(f"Tax (CGST {fmt_money(res.cgst_total)} + "
                                       f"SGST {fmt_money(res.sgst_total)})")
        else:
            self.lbl["tax"][0].setText("Tax")
        self.lbl["tax"][1].setText(m(res.tax_total))
        show_round = bool(res.round_off)
        for w in self.lbl["round"]:
            w.setVisible(show_round)
        self.lbl["round"][1].setText(m(res.round_off))
        self.grand.setText(m(res.grand_total))
        self.checkout_btn.setEnabled(bool(self.cart))
        bill = ""
        if self.bill_disc_percent is not None:
            bill = f" ({fmt_qty(self.bill_disc_percent)}% bill)"
        elif self.bill_disc_amount:
            bill = " (incl. bill discount)"
        self.lbl["discount"][0].setText("Discount" + bill)

    # ---- discounts / customer ---------------------------------------------------------
    def item_discount(self) -> None:
        if not self.ctx.can(Perm.APPLY_DISCOUNT):
            show_error(self, "You do not have permission to apply discounts.")
            return
        i = self._selected_index()
        if i is None:
            return
        ln = self.cart[i]
        gross = ln["product"]["selling_price"] * ln["qty"]
        dlg = DiscountDialog(self, f"Discount — {ln['product']['name']}", gross,
                             ln["disc_amount"], ln["disc_percent"], self.ctx)
        if dlg.exec() == QDialog.Accepted:
            ln["disc_amount"], ln["disc_percent"] = dlg.value()
            self.refresh_cart(select=i)

    def bill_discount(self) -> None:
        if not self.ctx.can(Perm.APPLY_DISCOUNT):
            show_error(self, "You do not have permission to apply discounts.")
            return
        if not self.cart or self.result is None:
            return
        dlg = DiscountDialog(self, "Bill discount", self.result.subtotal, self.bill_disc_amount,
                             self.bill_disc_percent, self.ctx)
        if dlg.exec() == QDialog.Accepted:
            self.bill_disc_amount, self.bill_disc_percent = dlg.value()
            self.recalc()

    def pick_customer(self) -> None:
        dlg = CustomerPicker(self, self.ctx)
        if dlg.exec() == QDialog.Accepted:
            self.customer = dlg.selected
            self.customer_btn.setText(
                f"Customer: {self.customer['name']}  (F4)" if self.customer
                else "Customer: Walk-in  (F4)")

    # ---- checkout -----------------------------------------------------------------------
    @ui_action
    def checkout(self) -> None:
        if not self.cart:
            return
        res = self.compute()
        req = SaleRequest(
            lines=[SaleLineRequest(ln["product"]["id"], ln["qty"], ln["disc_amount"],
                                   ln["disc_percent"]) for ln in self.cart],
            customer_id=self.customer["id"] if self.customer else None,
            bill_discount_amount=self.bill_disc_amount,
            bill_discount_percent=self.bill_disc_percent,
            tax_mode=self.tax_mode.currentData())
        dlg = CheckoutDialog(self, self.ctx, res, req)
        if dlg.exec() == QDialog.Accepted and dlg.sale:
            self.reset_sale()
