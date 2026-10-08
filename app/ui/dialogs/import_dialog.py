"""Bulk product import: template, check the file, then import all-or-nothing."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from app.services.errors import BusinessError
from app.services.product_import import COLUMNS, read_csv, write_template
from app.ui.widgets.common import button, confirm, handle_exception, label


class ImportProductsDialog(QDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.rows: list[dict] = []
        self.imported = 0
        self.setWindowTitle("Import products from CSV")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label("Import products from a spreadsheet", "SectionTitle"))
        lay.addWidget(label(
            "1. Save the template and fill it in Excel (one product per row), then save as "
            "“CSV UTF-8”.\n2. Choose the file. Every row is checked first; nothing is saved "
            "unless every row is valid.\n3. Click Import.  Required columns: "
            + ", ".join(c for c, req, _ in COLUMNS if req) + ".", "Muted", wrap=True))
        top = QHBoxLayout()
        top.addWidget(button("Save template…", None, self.save_template))
        top.addWidget(button("Choose CSV file…", "primary", self.choose_file))
        top.addStretch(1)
        lay.addLayout(top)
        self.file_lbl = label("No file chosen", "Faint")
        lay.addWidget(self.file_lbl)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlainText("Column guide:\n" + "\n".join(
            f"  {c}{' (required)' if req else ''}{' - ' + h if h else ''}"
            for c, req, h in COLUMNS))
        lay.addWidget(self.report, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(button("Close", None, self.reject))
        self.import_btn = button("Import", "primary", self.do_import)
        self.import_btn.setEnabled(False)
        bottom.addWidget(self.import_btn)
        lay.addLayout(bottom)

    def save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save product template",
                                              "BusinessPOS-products-template.csv",
                                              "CSV files (*.csv)")
        if path:
            try:
                write_template(path)
                self.file_lbl.setText(f"Template saved: {path}")
            except OSError as exc:
                handle_exception(self, BusinessError(f"The template could not be saved: {exc}"))

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose product file", "",
                                              "CSV files (*.csv);;All files (*)")
        if path:
            self.check_file(path)

    def check_file(self, path: str) -> None:
        self.import_btn.setEnabled(False)
        self.rows = []
        self.file_lbl.setText(Path(path).name)
        try:
            rows = read_csv(path)
            res = self.ctx.services.product_import.import_rows(self.ctx.user, rows, dry_run=True)
        except BusinessError as exc:
            self.report.setPlainText(f"This file cannot be imported:\n\n{exc}")
            return
        except OSError as exc:
            self.report.setPlainText(f"The file could not be opened:\n\n{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        if not res.ok:
            self.report.setPlainText(
                f"{len(res.errors)} problem(s) found - nothing will be imported until they are "
                f"fixed in the file:\n\n" + "\n".join(res.errors))
            return
        self.rows = rows
        text = f"Ready to import {res.created} product(s)."
        if res.new_categories:
            text += "\n\nNew categories that will be created:\n  " + \
                    "\n  ".join(res.new_categories)
        self.report.setPlainText(text)
        self.import_btn.setEnabled(True)

    def do_import(self):
        if not self.rows or not confirm(self, f"Import {len(self.rows)} product(s)?",
                                        yes_text="Import"):
            return
        try:
            res = self.ctx.services.product_import.import_rows(self.ctx.user, self.rows,
                                                               dry_run=False)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        if not res.ok:       # data changed since the check (e.g. another user)
            self.report.setPlainText("Nothing was imported:\n\n" + "\n".join(res.errors))
            self.import_btn.setEnabled(False)
            return
        self.imported = res.created
        self.accept()
