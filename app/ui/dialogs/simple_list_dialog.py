from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from app.reports.base import Col
from app.ui.widgets.common import button, label
from app.ui.widgets.table import DataTable


class ListDialog(QDialog):
    """Read-only list (history views)."""

    def __init__(self, parent, title: str, columns: list[Col], rows: list[dict],
                 subtitle: str = "", totals: dict | None = None, stretch: str | None = None,
                 extra_sections: list[tuple[str, list[Col], list[dict]]] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 580)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label(title, "SectionTitle"))
        if subtitle:
            lay.addWidget(label(subtitle, "Muted", wrap=True))
        t = DataTable(columns, stretch=stretch)
        t.set_rows(rows, totals=totals)
        lay.addWidget(t, 2)
        for sec_title, cols, sec_rows in extra_sections or []:
            lay.addWidget(label(sec_title, "SectionTitle"))
            t2 = DataTable(cols)
            t2.set_rows(sec_rows)
            lay.addWidget(t2, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Close", "primary", self.accept))
        lay.addLayout(row)
