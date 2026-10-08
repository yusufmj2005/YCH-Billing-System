"""Compare a day's Razorpay payments with the sales that recorded them."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from app.reports.base import Col
from app.ui.dialogs.razorpay_dialog import busy
from app.ui.styles.theme import C
from app.ui.widgets.common import button, date_edit, handle_exception, label, pydate
from app.ui.widgets.table import DataTable


class RazorpayCheckDialog(QDialog):
    def __init__(self, parent, ctx, day: date | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Check Razorpay payments")
        self.resize(980, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label("Every payment Razorpay received on the chosen day, and the invoice "
                            "that recorded it. A captured payment marked NOT RECORDED means the "
                            "money arrived but no sale was saved: ring the sale up again and "
                            "use Razorpay › Already paid? with that payment ID, or refund it "
                            "from the Razorpay Dashboard.", "Muted", wrap=True))
        row = QHBoxLayout()
        self.day = date_edit(day or date.today())
        row.addWidget(label("Day"))
        row.addWidget(self.day)
        row.addWidget(button("Check", "primary", self.load))
        row.addStretch(1)
        lay.addLayout(row)
        self.table = DataTable([Col("time", "Time", "datetime"), Col("payment_id", "Payment ID"),
                                Col("method", "Method"), Col("amount", "Amount", "money"),
                                Col("status", "Status"), Col("refunded", "Refunded", "money"),
                                Col("invoice", "Recorded on")], stretch="invoice")
        self.table.set_row_color(lambda r: C["danger"] if r["invoice"].startswith("NOT")
                                 or r["status"].startswith("Not found") else None)
        lay.addWidget(self.table, 1)
        self.summary = label("", "SectionTitle")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        close = QHBoxLayout()
        close.addStretch(1)
        close.addWidget(button("Close", None, self.accept))
        lay.addLayout(close)

    def load(self) -> bool:
        try:
            with busy():
                res = self.ctx.services.razorpay.reconcile(self.ctx.user, pydate(self.day.date()))
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return False
        self.data = res
        self.table.set_rows(res["rows"])
        m = self.ctx.money
        text = (f"Captured at Razorpay: {m(res['captured_total'])}   •   Recorded in "
                f"BusinessPOS: {m(res['recorded_total'])}")
        if res["not_recorded"]:
            text += f"   •   {res['not_recorded']} payment(s) NOT RECORDED"
        if res["unknown"]:
            text += f"   •   {res['unknown']} recorded payment(s) not found at Razorpay"
        if not res["not_recorded"] and not res["unknown"]:
            text += "   •   Everything matches ✓"
        self.summary.setText(text)
        return True
