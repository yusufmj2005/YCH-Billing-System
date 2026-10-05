from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import button, label, show_info, ui_action
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable

FIELDS = [Field("name", "Name", required=True, max_length=100),
          Field("description", "Description", "multiline"),
          Field("is_active", "Active", "check")]


class CategoriesPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        bar.addWidget(label("Categories group products in POS, reports and labels. Categories "
                            "that are in use can be deactivated but not deleted.", "Muted",
                            wrap=True), 1)
        bar.addWidget(button("New category", "primary", self.new))
        bar.addWidget(button("Edit", None, lambda: self.edit(self.table.selected())))
        self.root.addLayout(bar)
        self.table = DataTable([Col("name", "Category"), Col("description", "Description"),
                                Col("product_count", "Products", "int"),
                                Col("status", "Status")], stretch="description")
        self.table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.table.activated.connect(self.edit)
        self.root.addWidget(self.table, 1)

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        rows = self.ctx.services.catalog.list_categories(include_inactive=True)
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.table.set_rows(rows)

    def new(self):
        if FormDialog(self, "New category", FIELDS, {"is_active": True},
                      lambda d: self.ctx.services.catalog.save_category(self.ctx.user, None, d)
                      ).exec():
            self.load()

    def edit(self, row):
        if not row:
            show_info(self, "Select a category first.")
            return
        if FormDialog(self, "Edit category", FIELDS, row,
                      lambda d: self.ctx.services.catalog.save_category(self.ctx.user, row["id"],
                                                                        d)).exec():
            self.load()
