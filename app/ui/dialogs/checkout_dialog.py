"""Checkout (payments, split payments) and discount dialogs."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.config.constants import PaymentKind
from app.services.errors import ValidationError
from app.services.pricing import CartResult
from app.services.sales_service import PaymentRequest, SaleRequest
from app.ui import documents
from app.ui.widgets.common import button, handle_exception, icon_button, label, show_error
from app.ui.widgets.forms import decimal_edit
from app.utils.money import ZERO, fmt_money, money


class DiscountDialog(QDialog):
    """Discount as a fixed amount or a percentage of ``base``."""

    def __init__(self, parent, title: str, base: Decimal, amount: Decimal,
                 percent: Decimal | None, ctx):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.base = money(base)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.addWidget(label(f"Amount before discount: {ctx.money(self.base)}", "Muted"))
        row = QHBoxLayout()
        self.r_amt = QRadioButton("Amount")
        self.r_pct = QRadioButton("Percent")
        grp = QButtonGroup(self)
        grp.addButton(self.r_amt)
        grp.addButton(self.r_pct)
        row.addWidget(self.r_amt)
        row.addWidget(self.r_pct)
        row.addStretch(1)
        lay.addLayout(row)
        self.value_edit = decimal_edit(None, "0")
        lay.addWidget(self.value_edit)
        self.preview = label("", "Muted")
        lay.addWidget(self.preview)
        limit = ctx.settings.get("max_discount_percent")
        if limit not in (None, ""):
            lay.addWidget(label(f"Maximum total discount without approval: {limit}%", "Faint"))
        btns = QHBoxLayout()
        btns.addWidget(button("Remove discount", "ghost", self._clear))
        btns.addStretch(1)
        btns.addWidget(button("Cancel", None, self.reject))
        ok = button("Apply", "primary", self._ok)
        ok.setDefault(True)
        btns.addWidget(ok)
        lay.addLayout(btns)
        if percent is not None:
            self.r_pct.setChecked(True)
            self.value_edit.setText(f"{percent.normalize():f}")
        else:
            self.r_amt.setChecked(True)
            if amount:
                self.value_edit.setText(f"{amount:.2f}")
        self.value_edit.textChanged.connect(self._update)
        self.r_amt.toggled.connect(self._update)
        self._result = (ZERO, None)
        self._update()
        self.value_edit.setFocus()
        self.value_edit.selectAll()

    def _parse(self):
        txt = self.value_edit.text().strip() or "0"
        val = Decimal(txt)
        if self.r_pct.isChecked():
            if val > 100:
                raise ValidationError("Percentage cannot exceed 100.")
            return money(self.base * val / 100), val
        if val > self.base:
            raise ValidationError("Discount cannot exceed the amount.")
        return money(val), None

    def _update(self):
        try:
            amt, _ = self._parse()
            self.preview.setText(f"Discount: {fmt_money(amt)}   →   "
                                 f"After discount: {fmt_money(self.base - amt)}")
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(str(exc) if isinstance(exc, ValidationError) else "Invalid value")

    def _ok(self):
        try:
            amt, pct = self._parse()
        except Exception as exc:  # noqa: BLE001
            show_error(self, str(exc) if isinstance(exc, ValidationError) else "Invalid value.")
            return
        self._result = (ZERO if pct is not None else amt, pct)
        self.accept()

    def _clear(self):
        self._result = (ZERO, None)
        self.accept()

    def value(self) -> tuple[Decimal, Decimal | None]:
        return self._result


class CheckoutDialog(QDialog):
    def __init__(self, parent, ctx, result: CartResult, request: SaleRequest):
        super().__init__(parent)
        self.ctx = ctx
        self.res = result
        self.req = request
        self.sale = None
        self.payments: list[dict] = []
        self.methods = ctx.services.payment_methods.list()
        self.setWindowTitle("Checkout")
        self.setMinimumWidth(620)
        m = ctx.money

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)

        summary = QFrame()
        summary.setObjectName("TotalsPanel")
        sg = QGridLayout(summary)
        sg.setContentsMargins(16, 12, 16, 12)
        rows = [("Subtotal", m(result.gross_total)),
                ("Discount", ("-" + m(result.total_discount)) if result.total_discount else m(0)),
                ("Tax", m(result.tax_total))]
        if result.round_off:
            rows.append(("Round off", m(result.round_off)))
        for i, (a, b) in enumerate(rows):
            sg.addWidget(label(a, "Muted"), i, 0)
            lb = label(b)
            lb.setAlignment(Qt.AlignRight)
            sg.addWidget(lb, i, 1)
        sg.addWidget(label("Grand total", "SectionTitle"), len(rows), 0)
        gt = label(m(result.grand_total), "BigTotal")
        gt.setAlignment(Qt.AlignRight)
        sg.addWidget(gt, len(rows), 1)
        lay.addWidget(summary)

        lay.addWidget(label("Payment method", "SectionTitle"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.method_group = QButtonGroup(self)
        self.method_group.setExclusive(True)
        for i, pm in enumerate(self.methods):
            b = QPushButton(pm["name"])
            b.setCheckable(True)
            b.setProperty("variant", "pay")
            b.setCursor(Qt.PointingHandCursor)
            if i < 9:
                b.setShortcut(f"Alt+{i + 1}")
                b.setToolTip(f"Alt+{i + 1}")
            self.method_group.addButton(b, i)
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)
        self.method_group.idClicked.connect(self._method_changed)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.amount = decimal_edit(None)
        self.reference = QLineEdit()
        self.reference.setMaxLength(100)
        self.reference.setPlaceholderText("Optional — from the UPI app / card slip / bank")
        self.description = QLineEdit()
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("e.g. Gift voucher, Cheque")
        self.cash_received = decimal_edit(None, "Cash handed over (optional)")
        self.change_lbl = label("", "SectionTitle")
        self.lbl_amount = QLabel("Amount")
        self.lbl_ref = QLabel("Transaction / Reference ID")
        self.lbl_desc = QLabel("Payment method description")
        self.lbl_cash = QLabel("Cash received")
        form.addRow(self.lbl_amount, self.amount)
        form.addRow(self.lbl_ref, self.reference)
        form.addRow(self.lbl_desc, self.description)
        form.addRow(self.lbl_cash, self.cash_received)
        form.addRow("", self.change_lbl)
        lay.addLayout(form)
        lay.addWidget(label("Never enter card numbers, CVV, PINs or UPI PINs. Only the "
                            "transaction / reference ID is recorded.", "Faint", wrap=True))
        self.cash_received.textChanged.connect(self._update_change)
        self.amount.textChanged.connect(self._update_change)

        add_row = QHBoxLayout()
        add_row.addWidget(label("Split payment: add each part separately.", "Faint"))
        add_row.addStretch(1)
        add_row.addWidget(button("Add payment", None, self._add_payment))
        lay.addLayout(add_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Method", "Reference / description", "Amount", ""])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 34)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMaximumHeight(130)
        self.table.hide()
        lay.addWidget(self.table)
        self.remaining_lbl = label("", "SectionTitle")
        lay.addWidget(self.remaining_lbl)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(button("Back to cart", None, self.reject))
        self.complete_btn = button("Complete sale  (Enter)", "success", self._complete)
        self.complete_btn.setDefault(True)
        self.complete_btn.setMinimumHeight(40)
        btns.addWidget(self.complete_btn)
        lay.addLayout(btns)

        if self.methods:
            cash = next((i for i, pm in enumerate(self.methods)
                         if pm["kind"] == PaymentKind.CASH), 0)
            self.method_group.button(cash).setChecked(True)
            self._method_changed(cash)
        self._refresh()

    # ---- helpers ----------------------------------------------------------------
    def _method(self) -> dict | None:
        i = self.method_group.checkedId()
        return self.methods[i] if i >= 0 else None

    def _remaining(self) -> Decimal:
        return self.res.grand_total - sum((p["amount"] for p in self.payments), ZERO)

    def _method_changed(self, _i: int) -> None:
        pm = self._method()
        if pm is None:
            return
        allows = pm["allows_reference"]
        self.reference.setVisible(allows)
        self.lbl_ref.setVisible(allows)
        req = pm["requires_description"]
        self.description.setVisible(req)
        self.lbl_desc.setVisible(req)
        is_cash = pm["kind"] == PaymentKind.CASH
        self.cash_received.setVisible(is_cash)
        self.lbl_cash.setVisible(is_cash)
        self.change_lbl.setVisible(is_cash)
        self.amount.setText(f"{self._remaining():.2f}")
        (self.reference if allows else self.amount).setFocus()
        self._update_change()

    def _update_change(self) -> None:
        try:
            recv = Decimal(self.cash_received.text() or "0")
            amt = Decimal(self.amount.text() or "0")
        except Exception:  # noqa: BLE001
            self.change_lbl.setText("")
            return
        if recv > 0:
            diff = recv - amt
            self.change_lbl.setText(f"Change to return: {self.ctx.money(diff)}" if diff >= 0
                                    else f"Short by {self.ctx.money(-diff)}")
        else:
            self.change_lbl.setText("")

    def _add_payment(self) -> bool:
        pm = self._method()
        if pm is None:
            show_error(self, "Select a payment method.")
            return False
        try:
            amt = money(Decimal(self.amount.text() or "0"))
        except Exception:  # noqa: BLE001
            show_error(self, "Enter a valid amount.")
            return False
        if amt <= 0:
            show_error(self, "Payment amount must be greater than zero.")
            return False
        if amt > self._remaining():
            show_error(self, f"Amount exceeds the remaining balance "
                             f"({self.ctx.money(self._remaining())}).")
            return False
        if pm["requires_description"] and not self.description.text().strip():
            show_error(self, "Please describe the payment method.")
            self.description.setFocus()
            return False
        self.payments.append({"method": pm, "amount": amt,
                              "reference": self.reference.text().strip()
                              if pm["allows_reference"] else "",
                              "description": self.description.text().strip()
                              if pm["requires_description"] else ""})
        self.reference.clear()
        self.description.clear()
        self.cash_received.clear()
        self._refresh()
        self.amount.setText(f"{self._remaining():.2f}")
        return True

    def _remove_payment(self, row: int) -> None:
        if 0 <= row < len(self.payments):
            self.payments.pop(row)
            self._refresh()
            self.amount.setText(f"{self._remaining():.2f}")

    def _refresh(self) -> None:
        self.table.setVisible(bool(self.payments))
        self.table.setRowCount(len(self.payments))
        for i, p in enumerate(self.payments):
            self.table.setItem(i, 0, QTableWidgetItem(p["method"]["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(
                " • ".join(x for x in (p["description"], p["reference"]) if x)))
            a = QTableWidgetItem(fmt_money(p["amount"]))
            a.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 2, a)
            self.table.setCellWidget(i, 3, icon_button(
                "✕", lambda _=False, r=i: self._remove_payment(r), "Remove payment"))
        rem = self._remaining()
        if self.payments:
            self.remaining_lbl.setText(f"Paid {self.ctx.money(self.res.grand_total - rem)}"
                                       f"   •   Remaining {self.ctx.money(rem)}")
        else:
            self.remaining_lbl.setText("")

    # ---- completion -----------------------------------------------------------------
    def _complete(self) -> None:
        if self._remaining() > 0 and self.res.grand_total > 0:
            # Fast path: one payment for the whole remaining amount.
            if not self._add_payment():
                return
        if self._remaining() != 0:
            show_error(self, f"Payments must equal the grand total. Remaining: "
                             f"{self.ctx.money(self._remaining())}")
            return
        self.req.payments = [PaymentRequest(p["method"]["id"], p["amount"],
                                            p["reference"] or None, p["description"] or None)
                             for p in self.payments]
        try:
            self.sale = self.ctx.services.sales.create_sale(self.ctx.user, self.req)
        except Exception as exc:  # noqa: BLE001
            self.payments.clear()
            self._refresh()
            self.amount.setText(f"{self._remaining():.2f}")
            handle_exception(self, exc)
            return
        self.ctx.toast(f"Sale {self.sale['invoice_no']} completed")
        if self.ctx.settings.get("auto_print_invoice"):
            try:
                documents.print_invoice(self.ctx, self, self.sale["sale_id"], ask=False)
            except Exception as exc:  # noqa: BLE001
                handle_exception(self, exc)
        SaleCompleteDialog(self, self.ctx, self.sale, self._change_text()).exec()
        self.accept()

    def _change_text(self) -> str:
        try:
            recv = Decimal(self.cash_received.text() or "0")
        except Exception:  # noqa: BLE001
            return ""
        cash_paid = sum((p["amount"] for p in self.payments
                         if p["method"]["kind"] == PaymentKind.CASH), ZERO)
        if recv > 0 and cash_paid and recv >= cash_paid:
            return f"Change to return: {self.ctx.money(recv - cash_paid)}"
        return ""


class SaleCompleteDialog(QDialog):
    def __init__(self, parent, ctx, sale: dict, change_text: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.sale = sale
        self.setWindowTitle("Sale completed")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        t = label("Sale completed", "PageTitle")
        lay.addWidget(t)
        lay.addWidget(label(f"Invoice {sale['invoice_no']}", "Muted"))
        lay.addWidget(label(ctx.money(sale["grand_total"]), "BigTotal"))
        if change_text:
            ch = label(change_text, "SectionTitle")
            lay.addWidget(ch)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addWidget(button("Print invoice (P)", None, self._print))
        row.addWidget(button("Open PDF", None, self._open))
        row.addStretch(1)
        new = button("New sale (Enter)", "primary", self.accept)
        new.setDefault(True)
        row.addWidget(new)
        lay.addLayout(row)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("P"), self, activated=self._print)

    def _print(self):
        try:
            if documents.print_invoice(self.ctx, self, self.sale["sale_id"]):
                self.ctx.toast("Invoice sent to printer")
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)

    def _open(self):
        try:
            documents.open_invoice(self.ctx, self, self.sale["sale_id"])
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
