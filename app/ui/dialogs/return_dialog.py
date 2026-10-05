"""Process a return against an original invoice."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.config.constants import SaleStatus
from app.printing.printer import print_pdf
from app.services.errors import BusinessError, ValidationError
from app.services.return_service import ReturnLineRequest, ReturnRequest
from app.services.sales_service import PaymentRequest
from app.ui import documents
from app.ui.widgets.common import (button, confirm, handle_exception, label, show_error,
                                   show_info)
from app.ui.widgets.forms import decimal_edit
from app.utils.dates import fmt_dt
from app.utils.money import ZERO, fmt_money, fmt_qty, money


class ReturnDialog(QDialog):
    def __init__(self, parent, ctx, invoice_no: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.sale = None
        self.refund_total = ZERO
        self.result_return = None
        self.setWindowTitle("New return")
        self.resize(920, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.invoice = QLineEdit(invoice_no)
        self.invoice.setPlaceholderText("Original invoice number")
        self.invoice.returnPressed.connect(self.load)
        top.addWidget(label("Invoice", "SectionTitle"))
        top.addWidget(self.invoice, 1)
        top.addWidget(button("Load invoice", "primary", self.load))
        lay.addLayout(top)
        self.info = label("Enter the invoice number from the customer's receipt.", "Muted")
        lay.addWidget(self.info)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Product", "Sold", "Already returned",
                                              "Returnable", "Return qty", "Back to stock",
                                              "Refund"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        lay.addWidget(self.table, 1)

        form = QFormLayout()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Required, e.g. wrong colour, defective")
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(48)
        form.addRow("Reason *", self.reason)
        form.addRow("Notes", self.notes)
        lay.addLayout(form)

        lay.addWidget(label("Refund", "SectionTitle"))
        self.refund_lbl = label("Refund total: 0.00", "SectionTitle")
        lay.addWidget(self.refund_lbl)
        self.refund_rows: list[tuple[QComboBox, QLineEdit, QLineEdit]] = []
        self.refund_box = QVBoxLayout()
        lay.addLayout(self.refund_box)
        lay.addWidget(button("Split refund across another method", "ghost",
                             lambda: self._add_refund_row()))
        lay.addWidget(label("The refund must equal the refund total. Do not enter card numbers.",
                            "Faint"))
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(button("Cancel", None, self.reject))
        self.process_btn = button("Process return", "success", self.process)
        self.process_btn.setEnabled(False)
        btns.addWidget(self.process_btn)
        lay.addLayout(btns)
        self.methods = ctx.services.payment_methods.list()
        if invoice_no:
            self.load()

    def _add_refund_row(self, amount: Decimal | None = None):
        row = QHBoxLayout()
        combo = QComboBox()
        for pm in self.methods:
            combo.addItem(pm["name"], pm["id"])
        amt = decimal_edit(f"{amount:.2f}" if amount is not None else None)
        amt.setMaximumWidth(140)
        ref = QLineEdit()
        ref.setPlaceholderText("Reference ID (optional)")
        row.addWidget(combo)
        row.addWidget(amt)
        row.addWidget(ref, 1)
        w = QWidget()
        w.setLayout(row)
        self.refund_box.addWidget(w)
        self.refund_rows.append((combo, amt, ref))
        return combo

    def load(self):
        try:
            sale = self.ctx.services.sales.get_sale(self.ctx.user,
                                                    invoice_no=self.invoice.text().strip())
        except BusinessError as exc:
            show_error(self, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        if sale["status"] != SaleStatus.COMPLETED:
            show_error(self, "This invoice was voided; returns are not possible.")
            return
        self.sale = sale
        self.info.setText(f"{sale['invoice_no']} • {fmt_dt(sale['created_at'])} • "
                          f"{sale['customer_name'] or 'Walk-in'} • total "
                          f"{self.ctx.money(sale['grand_total'])}")
        self.table.setRowCount(len(sale["items"]))
        self.qty_edits = []
        self.restock_checks = []
        for i, it in enumerate(sale["items"]):
            returnable = it["quantity"] - it["returned_quantity"]
            vals = [it["product_name"], fmt_qty(it["quantity"]), fmt_qty(it["returned_quantity"]),
                    fmt_qty(returnable)]
            for c, text in enumerate(vals):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if c:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, cell)
            q = decimal_edit(None, "0")
            q.setEnabled(returnable > 0)
            q.textChanged.connect(self._recalc)
            self.table.setCellWidget(i, 4, q)
            chk = QCheckBox()
            chk.setChecked(True)
            chk.setToolTip("Untick for damaged items that cannot be resold")
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(12, 0, 0, 0)
            hl.addWidget(chk)
            self.table.setCellWidget(i, 5, holder)
            self.table.setItem(i, 6, QTableWidgetItem(""))
            self.qty_edits.append(q)
            self.restock_checks.append(chk)
        while self.refund_rows:
            combo, _, _ = self.refund_rows.pop()
            combo.parentWidget().deleteLater()
        combo = self._add_refund_row()
        if sale["payments"]:
            idx = combo.findText(sale["payments"][0]["method"])
            if idx >= 0:
                combo.setCurrentIndex(idx)
        self._recalc()

    def _lines(self) -> list[ReturnLineRequest]:
        out = []
        for it, q, chk in zip(self.sale["items"], self.qty_edits, self.restock_checks):
            txt = q.text().strip()
            if txt and Decimal(txt) > 0:
                out.append(ReturnLineRequest(it["id"], Decimal(txt), chk.isChecked()))
        return out

    def _recalc(self):
        if not self.sale:
            return
        lines = self._lines()
        self.process_btn.setEnabled(bool(lines))
        if not lines:
            self.refund_total = ZERO
            self.refund_lbl.setText(f"Refund total: {self.ctx.money(0)}")
            return
        try:
            prev = self.ctx.services.returns.preview(self.ctx.user, self.sale["id"], lines)
        except ValidationError as exc:
            self.refund_lbl.setText(str(exc))
            self.process_btn.setEnabled(False)
            return
        self.refund_total = prev["refund_total"]
        self.refund_lbl.setText(f"Refund total: {self.ctx.money(self.refund_total)}  "
                                f"(taxable {fmt_money(prev['taxable_total'])} + tax "
                                f"{fmt_money(prev['tax_total'])})")
        if len(self.refund_rows) == 1:
            self.refund_rows[0][1].setText(f"{self.refund_total:.2f}")

    def process(self):
        if not self.sale:
            return
        refunds = []
        for combo, amt, ref in self.refund_rows:
            text = amt.text().strip()
            if text and Decimal(text) > 0:
                refunds.append(PaymentRequest(combo.currentData(), money(Decimal(text)),
                                              ref.text().strip() or None,
                                              description="Refund"))
        if not confirm(self, f"Process this return and refund "
                             f"{self.ctx.money(self.refund_total)}?"):
            return
        try:
            res = self.ctx.services.returns.create_return(self.ctx.user, ReturnRequest(
                sale_id=self.sale["id"], lines=self._lines(), reason=self.reason.text(),
                refunds=refunds, notes=self.notes.toPlainText()))
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.result_return = res
        self.ctx.toast(f"Return {res['return_no']} processed")
        if confirm(self, f"Return {res['return_no']} recorded. Refund "
                         f"{self.ctx.money(res['refund_total'])}.\n\nPrint a return note?",
                   title="Return processed", yes_text="Print"):
            try:
                print_pdf(self, documents.return_pdf(self.ctx, res["return_id"]))
            except Exception as exc:  # noqa: BLE001
                handle_exception(self, exc)
        self.accept()
