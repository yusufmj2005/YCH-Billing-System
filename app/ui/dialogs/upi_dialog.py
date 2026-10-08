"""Full-size UPI QR for the customer to scan."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.payments.upi import qr_matrix, upi_uri
from app.ui.widgets.common import button, label
from app.utils.money import fmt_money


def qr_pixmap(text: str, size: int = 300) -> QPixmap:
    """Render ``text`` as a QR code with the standard 4-module quiet zone."""
    m = qr_matrix(text)
    n = len(m) + 8
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    cell = size / n
    for r, row in enumerate(m):
        for c, dark in enumerate(row):
            if dark:
                p.drawRect(QRectF((c + 4) * cell, (r + 4) * cell, cell + 0.5, cell + 0.5))
    p.end()
    return QPixmap.fromImage(img)


class UpiQrDialog(QDialog):
    """Shows the QR; *Payment received* confirms that the cashier saw the money arrive."""

    def __init__(self, parent, upi_id: str, payee: str, amount: Decimal, note: str = ""):
        super().__init__(parent)
        self.uri = upi_uri(upi_id, payee, amount, note)   # validates; raises BusinessError
        self.setWindowTitle("Scan to pay with UPI")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        title = label(f"Pay ₹{fmt_money(amount)}", "PageTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        qr = QLabel()
        qr.setPixmap(qr_pixmap(self.uri))
        qr.setAlignment(Qt.AlignCenter)
        lay.addWidget(qr)
        who = label(f"{payee}\n{upi_id}", "Muted")
        who.setAlignment(Qt.AlignCenter)
        lay.addWidget(who)
        lay.addWidget(label("Ask the customer to scan with any UPI app (GPay, PhonePe, Paytm, "
                            "BHIM…). Click Payment received only after your UPI app or "
                            "soundbox confirms the money has arrived.", "Faint", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", None, self.reject))
        ok = button("Payment received", "success", self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
