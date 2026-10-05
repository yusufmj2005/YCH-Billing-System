"""Declarative form dialog used for most simple create/edit screens.

The dialog calls ``on_submit(data)``; if it raises a BusinessError the message
is shown and the dialog stays open so the user can correct the input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout,
                               QWidget)

from app.ui.widgets.common import date_edit, handle_exception, label, pydate, qdate

DECIMAL_RE = QRegularExpression(r"^-?\d{0,12}([.,]\d{0,3})?$")


def decimal_edit(value=None, placeholder: str = "0.00", allow_negative: bool = False) -> QLineEdit:
    e = QLineEdit()
    rx = r"^-?\d{0,12}(\.\d{0,3})?$" if allow_negative else r"^\d{0,12}(\.\d{0,3})?$"
    e.setValidator(QRegularExpressionValidator(QRegularExpression(rx), e))
    e.setPlaceholderText(placeholder)
    e.setAlignment(Qt.AlignRight)
    if value is not None and value != "":
        e.setText(f"{value}")
    return e


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"  # text|multiline|money|decimal|combo|check|date|optdate|password|time
    required: bool = False
    options: list[tuple[str, Any]] = field(default_factory=list)
    placeholder: str = ""
    help: str = ""
    max_length: int | None = None
    readonly: bool = False


class FormDialog(QDialog):
    def __init__(self, parent, title: str, fields: list[Field], values: dict | None = None,
                 on_submit: Callable[[dict], Any] | None = None, intro: str = "",
                 submit_text: str = "Save", width: int = 480):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.fields = fields
        self.on_submit = on_submit
        self.result_value = None
        self.widgets: dict[str, QWidget] = {}
        values = values or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        if intro:
            root.addWidget(label(intro, "Muted", wrap=True))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        for f in fields:
            w = self._make_widget(f, values.get(f.key))
            self.widgets[f.key] = w
            text = f.label + (" *" if f.required else "")
            if f.help:
                box = QWidget()
                v = QVBoxLayout(box)
                v.setContentsMargins(0, 0, 0, 0)
                v.setSpacing(2)
                v.addWidget(w)
                v.addWidget(label(f.help, "Faint", wrap=True))
                form.addRow(text, box)
            else:
                form.addRow(text, w)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(submit_text)
        buttons.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _make_widget(self, f: Field, value) -> QWidget:
        if f.kind == "multiline":
            w = QPlainTextEdit()
            w.setPlainText(value or "")
            w.setFixedHeight(72)
        elif f.kind in ("money", "decimal"):
            w = decimal_edit(value, f.placeholder or ("0.00" if f.kind == "money" else ""))
        elif f.kind == "combo":
            w = QComboBox()
            for text, data in f.options:
                w.addItem(text, data)
            idx = w.findData(value)
            if idx >= 0:
                w.setCurrentIndex(idx)
        elif f.kind == "check":
            w = QCheckBox()
            w.setChecked(bool(value) if value is not None else False)
        elif f.kind == "date":
            w = date_edit(value if isinstance(value, date) else None)
        elif f.kind == "optdate":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox("Set")
            de = date_edit(value if isinstance(value, date) else None)
            chk.setChecked(isinstance(value, date))
            de.setEnabled(chk.isChecked())
            chk.toggled.connect(de.setEnabled)
            h.addWidget(chk)
            h.addWidget(de, 1)
            w._chk, w._de = chk, de
        else:
            w = QLineEdit()
            if f.kind == "password":
                w.setEchoMode(QLineEdit.Password)
            if f.kind == "time":
                w.setPlaceholderText(f.placeholder or "HH:MM")
                w.setInputMask("")
            w.setText("" if value is None else str(value))
            if f.placeholder:
                w.setPlaceholderText(f.placeholder)
            if f.max_length:
                w.setMaxLength(f.max_length)
        if f.readonly:
            w.setEnabled(False)
        return w

    def data(self) -> dict:
        out = {}
        for f in self.fields:
            w = self.widgets[f.key]
            if f.kind == "multiline":
                out[f.key] = w.toPlainText()
            elif f.kind == "combo":
                out[f.key] = w.currentData()
            elif f.kind == "check":
                out[f.key] = w.isChecked()
            elif f.kind == "date":
                out[f.key] = pydate(w.date())
            elif f.kind == "optdate":
                out[f.key] = pydate(w._de.date()) if w._chk.isChecked() else None
            else:
                out[f.key] = w.text()
        return out

    def _submit(self) -> None:
        data = self.data()
        for f in self.fields:
            if f.required and f.kind not in ("check",) and (data.get(f.key) in (None, "")):
                from app.ui.widgets.common import show_error
                show_error(self, f"{f.label} is required.")
                self.widgets[f.key].setFocus()
                return
        if self.on_submit:
            try:
                self.result_value = self.on_submit(data)
            except Exception as exc:  # noqa: BLE001
                handle_exception(self, exc)
                return
        self.accept()


def set_date(w, d: date) -> None:
    w.setDate(qdate(d))


def as_decimal(text: str) -> Decimal | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None
