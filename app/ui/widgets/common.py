"""Shared UI helpers: safe action wrapper, message boxes, cards, toasts,
date-range filter."""
from __future__ import annotations

import functools
import inspect
import logging
from datetime import date

from PySide6.QtCore import QDate, QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from app.services.errors import BusinessError
from app.utils.dates import preset_range

log = logging.getLogger(__name__)

GENERIC_ERROR = ("Something went wrong and the action was not completed.\n"
                 "No data was changed. Please try again; if the problem continues, "
                 "contact your administrator (details were written to the log file).")


# ---------------------------------------------------------------- messages ----
def show_error(parent, message: str, title: str = "Unable to complete") -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent, message: str, title: str = "BusinessPOS") -> None:
    QMessageBox.information(parent, title, message)


def confirm(parent, message: str, title: str = "Please confirm", danger: bool = False,
            yes_text: str = "Yes") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(message)
    yes = box.addButton(yes_text, QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(QMessageBox.Cancel if danger else yes)
    box.exec()
    return box.clickedButton() is yes


def handle_exception(parent, exc: Exception) -> None:
    if isinstance(exc, BusinessError):
        show_error(parent, str(exc))
    else:
        log.exception("Unexpected error in UI action")
        show_error(parent, GENERIC_ERROR, "Unexpected error")


def ui_action(fn):
    """Decorator for slots: shows friendly messages instead of crashing.

    BusinessError messages are user-safe and shown as-is; anything else is
    logged with a stack trace and a generic message is shown."""
    try:
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        n_args = len(params)
    except (TypeError, ValueError):
        n_args = None

    @functools.wraps(fn)
    def wrapper(self, *args):
        if n_args is not None:
            args = args[: max(0, n_args - 1)]
        try:
            return fn(self, *args)
        except Exception as exc:  # noqa: BLE001 - deliberate UI boundary
            handle_exception(self if isinstance(self, QWidget) else None, exc)
            return None
    return wrapper


# ---------------------------------------------------------------- widgets ----
def button(text: str, variant: str | None = None, slot=None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if slot:
        b.clicked.connect(slot)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def icon_button(text: str, slot=None, tooltip: str = "") -> QPushButton:
    """Small borderless button for table rows (e.g. remove ✕)."""
    b = button(text, "icon", slot, tooltip)
    b.setFixedSize(26, 24)
    return b


def clear_layout(layout) -> None:
    """Remove and destroy every widget in ``layout`` immediately."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


class Card(QFrame):
    def __init__(self, parent=None, padding: int = 16, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(spacing)


class StatCard(Card):
    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(parent, padding=14, spacing=2)
        self.title = label(title, "StatLabel")
        self.value = label("0", "StatValue")
        self.hint = label(hint, "Faint")
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.hint)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, hint: str | None = None) -> None:
        self.value.setText(value)
        if hint is not None:
            self.hint.setText(hint)


class Toast(QFrame):
    """Small transient confirmation message in the bottom-right corner."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.lab = QLabel()
        lay.addWidget(self.lab)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_message(self, text: str, ms: int = 3000) -> None:
        self.lab.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 24, p.height() - self.height() - 40)
        self.raise_()
        self.show()
        self._timer.start(ms)


def search_box(placeholder: str = "Search…", on_change=None, delay_ms: int = 250) -> QLineEdit:
    box = QLineEdit()
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    box.setMinimumWidth(240)
    if on_change:
        timer = QTimer(box, singleShot=True, interval=delay_ms, timeout=on_change)
        box.textChanged.connect(lambda _t: timer.start())
        box._debounce = timer  # keep reference
    return box


def qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def date_edit(d: date | None = None) -> QDateEdit:
    e = QDateEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("dd-MM-yyyy")
    e.setDate(qdate(d or date.today()))
    return e


class DateRangeBar(QWidget):
    """Preset selector (Today / This week / This month / ...) + custom range."""
    changed = Signal()

    PRESETS = [("Today", "today"), ("Yesterday", "yesterday"), ("This week", "this_week"),
               ("This month", "this_month"), ("Last month", "last_month"),
               ("Last 30 days", "last_30"), ("This year", "this_year"), ("Custom range", "custom")]

    def __init__(self, default: str = "today", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.preset = QComboBox()
        for text, key in self.PRESETS:
            self.preset.addItem(text, key)
        self.start = date_edit()
        self.end = date_edit()
        lay.addWidget(self.preset)
        lay.addWidget(self.start)
        lay.addWidget(QLabel("to"))
        lay.addWidget(self.end)
        idx = self.preset.findData(default)
        self.preset.setCurrentIndex(max(0, idx))
        self._apply_preset()
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.start.dateChanged.connect(self._custom_changed)
        self.end.dateChanged.connect(self._custom_changed)

    def _apply_preset(self) -> None:
        key = self.preset.currentData()
        custom = key == "custom"
        self.start.setEnabled(custom)
        self.end.setEnabled(custom)
        if not custom:
            a, b = preset_range(key)
            for w, d in ((self.start, a), (self.end, b)):
                w.blockSignals(True)
                w.setDate(qdate(d))
                w.blockSignals(False)

    def _preset_changed(self) -> None:
        self._apply_preset()
        self.changed.emit()

    def _custom_changed(self) -> None:
        if self.preset.currentData() == "custom":
            self.changed.emit()

    def range(self) -> tuple[date, date]:
        a, b = pydate(self.start.date()), pydate(self.end.date())
        return (a, b) if a <= b else (b, a)

    def description(self) -> str:
        a, b = self.range()
        if a == b:
            return a.strftime("%d-%m-%Y")
        return f"{a:%d-%m-%Y} to {b:%d-%m-%Y}"


class PageHeader(QWidget):
    """Row with a muted description on the left and action buttons right."""

    def __init__(self, description: str = "", parent=None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.desc = label(description, "Muted", wrap=True)
        self.lay.addWidget(self.desc, 1)

    def add(self, *widgets) -> None:
        for w in widgets:
            self.lay.addWidget(w)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #E2E5EA;")
    return f
