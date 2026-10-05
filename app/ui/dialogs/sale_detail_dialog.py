from __future__ import annotations

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QInputDialog, QVBoxLayout

from app.config.constants import TAX_MODE_LABELS, Perm, SaleStatus
from app.reports.base import Col
from app.ui import documents
from app.ui.widgets.common import Card, button, confirm, label, ui_action
from app.ui.widgets.table import DataTable
from app.utils.dates import fmt_dt


class SaleDetailDialog(QDialog):
    def __init__(self, parent, ctx, sale_id: int):
        super().__init__(parent)
        self.ctx = ctx
        self.sale_id = sale_id
        self.changed = False
        self.setWindowTitle("Sale details")
        self.resize(900, 640)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 16, 20, 16)
        self.lay.setSpacing(10)
        self._build()

    def _build(self):
        ctx = self.ctx
        s = ctx.services.sales.get_sale(ctx.user, self.sale_id)
        self.sale = s
        m = ctx.money
        head = QHBoxLayout()
        title = label(f"Invoice {s['invoice_no']}", "PageTitle")
        head.addWidget(title)
        status = label(s["status"].title(), "Warning" if s["status"] == SaleStatus.VOIDED
                       else "Notice")
        head.addWidget(status)
        head.addStretch(1)
        self.lay.addLayout(head)
        info = QGridLayout()
        info.setHorizontalSpacing(24)
        pairs = [("Date", fmt_dt(s["created_at"])), ("Billed by", s["cashier"]),
                 ("Customer", s["customer_name"] or "Walk-in"),
                 ("Phone", s["customer_phone"] or "—"),
                 ("Tax type", TAX_MODE_LABELS.get(s["tax_mode"], s["tax_mode"])),
                 ("Customer GSTIN", s["customer_gstin"] or "—")]
        for i, (a, b) in enumerate(pairs):
            info.addWidget(label(a, "Muted"), i // 3, (i % 3) * 2)
            info.addWidget(label(b), i // 3, (i % 3) * 2 + 1)
        self.lay.addLayout(info)
        if s["status"] == SaleStatus.VOIDED:
            self.lay.addWidget(label(f"Voided on {fmt_dt(s['voided_at'])}. Reason: "
                                     f"{s['void_reason']}", "Warning", wrap=True))
        items = DataTable([Col("product_name", "Product"), Col("quantity", "Qty", "qty"),
                           Col("unit_price", "Price", "money"),
                           Col("discount_amount", "Item disc.", "money"),
                           Col("bill_discount_share", "Bill disc.", "money"),
                           Col("taxable_amount", "Taxable", "money"),
                           Col("tax_rate", "Tax %", "pct"), Col("tax_amount", "Tax", "money"),
                           Col("line_total", "Total", "money"),
                           Col("returned_quantity", "Returned", "qty")], stretch="product_name")
        items.set_rows(s["items"])
        self.lay.addWidget(items, 1)

        bottom = QHBoxLayout()
        pay_card = Card()
        pay_card.lay.addWidget(label("Payments", "SectionTitle"))
        for p in s["payments"]:
            txt = f"{p['method']}: {m(p['amount'])}"
            if p["description"]:
                txt += f"  ({p['description']})"
            if p["reference"]:
                txt += f"   Ref: {p['reference']}"
            if p["is_void"]:
                txt += "   [void]"
            pay_card.lay.addWidget(label(txt))
        if not s["payments"]:
            pay_card.lay.addWidget(label("No payment (zero total).", "Muted"))
        if s["returns"]:
            pay_card.lay.addWidget(label("Returns", "SectionTitle"))
            for r in s["returns"]:
                pay_card.lay.addWidget(label(f"{r['return_no']} — {fmt_dt(r['created_at'])}"
                                             f" — refund {m(r['refund_total'])}"))
        pay_card.lay.addStretch(1)
        bottom.addWidget(pay_card, 1)
        tot = Card()
        g = QGridLayout()
        rows = [("Gross", s["gross_total"]), ("Item discounts", -s["item_discount_total"]),
                ("Bill discount", -s["bill_discount"]), ("Taxable value", s["taxable_total"]),
                ("CGST", s["cgst_total"]), ("SGST", s["sgst_total"]), ("IGST", s["igst_total"]),
                ("Round off", s["round_off"])]
        r = 0
        for a, b in rows:
            if b or a in ("Gross", "Taxable value"):
                g.addWidget(label(a, "Muted"), r, 0)
                g.addWidget(label(m(b)), r, 1)
                r += 1
        g.addWidget(label("Grand total", "SectionTitle"), r, 0)
        g.addWidget(label(m(s["grand_total"]), "SectionTitle"), r, 1)
        tot.lay.addLayout(g)
        bottom.addWidget(tot)
        self.lay.addLayout(bottom)

        btns = QHBoxLayout()
        btns.addWidget(button("Print", None, self._print))
        btns.addWidget(button("Open PDF", None, self._open))
        btns.addWidget(button("Save PDF as…", None, self._save))
        btns.addWidget(button("Print 80 mm receipt", None, self._receipt))
        btns.addStretch(1)
        if ctx.can(Perm.CANCEL_SALE) and s["status"] == SaleStatus.COMPLETED and not s["returns"]:
            btns.addWidget(button("Void sale…", "danger", self._void))
        btns.addWidget(button("Close", "primary", self.accept))
        self.lay.addLayout(btns)

    @ui_action
    def _print(self):
        if documents.print_invoice(self.ctx, self, self.sale_id):
            self.ctx.toast("Invoice sent to printer")

    @ui_action
    def _open(self):
        documents.open_invoice(self.ctx, self, self.sale_id)

    @ui_action
    def _save(self):
        documents.save_invoice_as(self.ctx, self, self.sale_id)

    @ui_action
    def _receipt(self):
        from app.printing.printer import print_pdf
        path = documents.invoice_pdf(self.ctx, self.sale_id, paper="RECEIPT_80MM")
        print_pdf(self, path, title="Print receipt")

    @ui_action
    def _void(self):
        reason, ok = QInputDialog.getText(
            self, "Void sale", f"Void invoice {self.sale['invoice_no']}?\n\nStock will be "
            "restored and the payments marked void. The invoice number is not reused.\n\n"
            "Reason (required):")
        if not ok:
            return
        if not confirm(self, f"Void invoice {self.sale['invoice_no']}? This cannot be undone.",
                       danger=True, yes_text="Void sale"):
            return
        self.ctx.services.sales.void_sale(self.ctx.user, self.sale_id, reason)
        self.changed = True
        self.ctx.toast(f"Invoice {self.sale['invoice_no']} voided")
        self.accept()
