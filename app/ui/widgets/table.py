"""Generic read-only table bound to a list of dicts, with sorting and an
optional pager for large data sets."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableView, QVBoxLayout, QWidget)

from app.reports.base import Col, format_value

SORT_ROLE = Qt.UserRole + 1


class RecordModel(QAbstractTableModel):
    def __init__(self, columns: list[Col], parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = []
        self.row_color: Callable[[dict], str | None] | None = None
        self.total_row: dict | None = None

    def set_rows(self, rows: list[dict], totals: dict | None = None) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.total_row = totals
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + (1 if self.total_row else 0)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def _row(self, r: int) -> dict:
        return self.rows[r] if r < len(self.rows) else self.total_row

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._row(index.row())
        col = self.columns[index.column()]
        value = row.get(col.key)
        is_total = index.row() >= len(self.rows)
        if role == Qt.DisplayRole:
            return format_value(value, col.kind)
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignRight if col.numeric else Qt.AlignLeft) | Qt.AlignVCenter)
        if role == SORT_ROLE:
            if is_total:
                return None
            if isinstance(value, (Decimal, int, float)):
                return float(value)
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            return str(value or "").lower()
        if role == Qt.ForegroundRole and self.row_color and not is_total:
            color = self.row_color(row)
            return QColor(color) if color else None
        if role == Qt.FontRole and is_total:
            from PySide6.QtGui import QFont
            f = QFont()
            f.setBold(True)
            return f
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return self.columns[section].label
            if role == Qt.TextAlignmentRole:
                return int((Qt.AlignRight if self.columns[section].numeric else Qt.AlignLeft)
                           | Qt.AlignVCenter)
        return None


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        src = self.sourceModel()
        # keep the totals row at the bottom regardless of sort order
        if left.row() >= len(src.rows) or right.row() >= len(src.rows):
            asc = self.sortOrder() == Qt.AscendingOrder
            return (left.row() < right.row()) if asc else (left.row() > right.row())
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class DataTable(QWidget):
    activated = Signal(dict)       # double-click / Enter
    selectionChanged = Signal()
    pageRequested = Signal(int)    # offset

    def __init__(self, columns: list[Col], parent=None, page_size: int | None = None,
                 stretch: str | None = None):
        super().__init__(parent)
        self.model = RecordModel(columns, self)
        self.proxy = _Proxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        # keep the service's order until the user clicks a column header
        self.view.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.view.setSortingEnabled(True)
        self.proxy.sort(-1)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(32)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(stretch is None)
        self.view.setWordWrap(False)
        self.view.doubleClicked.connect(self._activated)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selectionChanged.emit())
        self._stretch = stretch

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.view)
        self.page_size = page_size
        self.offset = 0
        self.total = 0
        self.empty_label = QLabel("No records found.")
        self.empty_label.setObjectName("Faint")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        lay.addWidget(self.empty_label)
        if page_size:
            bar = QHBoxLayout()
            self.info = QLabel()
            self.info.setObjectName("Faint")
            self.prev_btn = QPushButton("‹ Previous")
            self.next_btn = QPushButton("Next ›")
            self.prev_btn.clicked.connect(lambda: self.pageRequested.emit(
                max(0, self.offset - self.page_size)))
            self.next_btn.clicked.connect(lambda: self.pageRequested.emit(
                self.offset + self.page_size))
            bar.addWidget(self.info)
            bar.addStretch(1)
            bar.addWidget(self.prev_btn)
            bar.addWidget(self.next_btn)
            lay.addLayout(bar)

    def set_rows(self, rows: list[dict], total: int | None = None, offset: int = 0,
                 totals: dict | None = None) -> None:
        self.model.set_rows(rows, totals)
        self.offset = offset
        self.total = total if total is not None else len(rows)
        self.empty_label.setVisible(not rows)
        if self.page_size:
            end = offset + len(rows)
            self.info.setText(f"Showing {offset + 1 if rows else 0}–{end} of {self.total}")
            self.prev_btn.setEnabled(offset > 0)
            self.next_btn.setEnabled(end < self.total)
        self.view.resizeColumnsToContents()
        hdr = self.view.horizontalHeader()
        for i in range(self.model.columnCount()):
            if hdr.sectionSize(i) > 360:
                hdr.resizeSection(i, 360)
            elif hdr.sectionSize(i) < 70:
                hdr.resizeSection(i, 70)
        if self._stretch:
            keys = [c.key for c in self.model.columns]
            if self._stretch in keys:
                hdr.setSectionResizeMode(keys.index(self._stretch), QHeaderView.Stretch)

    def set_row_color(self, fn: Callable[[dict], str | None]) -> None:
        self.model.row_color = fn

    def selected(self) -> dict | None:
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        src = self.proxy.mapToSource(idx[0])
        if src.row() >= len(self.model.rows):
            return None
        return self.model.rows[src.row()]

    def _activated(self, index) -> None:
        src = self.proxy.mapToSource(index)
        if src.row() < len(self.model.rows):
            self.activated.emit(self.model.rows[src.row()])
