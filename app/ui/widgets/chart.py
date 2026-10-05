"""Minimal bar chart painted with QPainter (real data only)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from app.ui.styles.theme import C
from app.utils.money import fmt_money


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list[tuple[date, Decimal]] = []
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self._bars: list[tuple[QRectF, str]] = []

    def set_points(self, points: list[tuple[date, Decimal]]) -> None:
        self.points = points
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -26)
        self._bars = []
        values = [v for _, v in self.points]
        peak = max(values) if values else Decimal(0)
        small = QFont("Segoe UI", 8)
        p.setFont(small)
        # baseline
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())
        if not self.points:
            return
        if peak <= 0:
            p.setPen(QColor(C["faint"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No sales recorded in this period")
            return
        n = len(self.points)
        slot = rect.width() / n
        bw = max(6.0, slot * 0.58)
        for i, (d, v) in enumerate(self.points):
            h = float(v / peak) * (rect.height() - 14) if peak else 0
            x = rect.left() + i * slot + (slot - bw) / 2
            bar = QRectF(x, rect.bottom() - h, bw, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["primary"] if i == n - 1 else "#9DBBF5"))
            if h > 0:
                p.drawRoundedRect(bar, 3, 3)
            self._bars.append((QRectF(rect.left() + i * slot, rect.top(), slot, rect.height()),
                               f"{d:%a %d %b}: {fmt_money(v)}"))
            if n <= 16 or i % 2 == 0:
                p.setPen(QColor(C["muted"]))
                p.drawText(QRectF(rect.left() + i * slot, rect.bottom() + 4, slot, 18),
                           Qt.AlignHCenter | Qt.AlignTop, d.strftime("%d"))
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(rect.left(), rect.top() - 4, rect.width(), 14),
                   Qt.AlignRight, f"Peak {fmt_money(peak)}")

    def mouseMoveEvent(self, e):
        for r, text in self._bars:
            if r.contains(e.position()):
                QToolTip.showText(e.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()
