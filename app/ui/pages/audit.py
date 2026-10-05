from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout

from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.widgets.common import DateRangeBar, label, search_box, ui_action
from app.ui.widgets.table import DataTable

PAGE = 200


class AuditPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.search = search_box("User, entity or details…", lambda: self.load(0))
        self.range = DateRangeBar("last_30")
        self.range.changed.connect(lambda: self.load(0))
        self.action = QComboBox()
        self.action.currentIndexChanged.connect(lambda: self.load(0))
        bar.addWidget(self.search)
        bar.addWidget(self.range)
        bar.addWidget(self.action)
        bar.addStretch(1)
        self.root.addLayout(bar)
        self.table = DataTable([Col("created_at", "Time", "datetime"), Col("username", "User"),
                                Col("action", "Action"), Col("entity", "Entity"),
                                Col("entity_id", "ID"), Col("details", "Details")],
                               page_size=PAGE, stretch="details")
        self.table.pageRequested.connect(self.load)
        self.root.addWidget(self.table, 1)
        self.root.addWidget(label("The audit log is read-only. Records cannot be edited or "
                                  "deleted from within the application.", "Faint"))

    def on_show(self):
        cur = self.action.currentData()
        self.action.blockSignals(True)
        self.action.clear()
        self.action.addItem("All actions", None)
        for a in self.ctx.services.audit.actions(self.ctx.user):
            self.action.addItem(a, a)
        self.action.setCurrentIndex(max(0, self.action.findData(cur)))
        self.action.blockSignals(False)
        self.load(0)

    @ui_action
    def load(self, offset: int = 0):
        a, b = self.range.range()
        rows, total = self.ctx.services.audit.list(
            self.ctx.user, date_from=a, date_to=b, action=self.action.currentData(),
            search=self.search.text(), limit=PAGE, offset=offset)
        self.table.set_rows(rows, total, offset)
