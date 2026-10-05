from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from app.reports.base import Col
from app.ui import documents
from app.ui.dialogs.return_dialog import ReturnDialog
from app.ui.pages.base import Page
from app.ui.widgets.common import DateRangeBar, button, search_box, show_info, ui_action
from app.ui.widgets.table import DataTable

PAGE = 100


class ReturnsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("Return no., invoice no. or customer…", lambda: self.load(0))
        self.range = DateRangeBar("this_month")
        self.range.changed.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.range)
        bar.addStretch(1)
        bar.addWidget(button("New return", "primary", self.new_return))
        self.root.addLayout(bar)
        self.table = DataTable([
            Col("return_no", "Return"), Col("created_at", "Date", "datetime"),
            Col("invoice_no", "Original invoice"), Col("customer", "Customer"),
            Col("items", "Lines", "int"), Col("refund_total", "Refund", "money"),
            Col("refund_methods", "Refunded via"), Col("reason", "Reason"),
            Col("user", "User")], page_size=PAGE, stretch="reason")
        self.table.pageRequested.connect(self.load)
        self.table.activated.connect(lambda r: self.open_note(r))
        self.root.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Open return note (PDF)", None,
                             lambda: self.open_note(self.table.selected())))
        self.root.addLayout(row)

    def on_show(self):
        self.load(0)

    @ui_action
    def load(self, offset: int = 0):
        a, b = self.range.range()
        rows, total = self.ctx.services.returns.list_returns(
            self.ctx.user, date_from=a, date_to=b, search=self.search.text(), limit=PAGE,
            offset=offset)
        self.table.set_rows(rows, total, offset)

    def new_return(self):
        dlg = ReturnDialog(self, self.ctx)
        if dlg.exec():
            self.load(0)

    @ui_action
    def open_note(self, row):
        if not row:
            show_info(self, "Select a return first.")
            return
        self.ctx.open_file(documents.return_pdf(self.ctx, row["id"]))
