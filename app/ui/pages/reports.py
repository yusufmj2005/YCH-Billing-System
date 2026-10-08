from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from app.config.constants import MOVEMENT_TYPE_LABELS, Perm
from app.reports.base import ReportResult
from app.reports.exporters import export_csv, export_pdf
from app.ui.pages.base import Page
from app.ui.widgets.common import (Card, DateRangeBar, button, clear_layout, label, show_info,
                                   ui_action)
from app.ui.widgets.table import DataTable

# key: (group, title, financial?, filters, callable(svc, user, f) -> ReportResult)
R = {
    "daily": ("Sales", "Daily sales", False, {"range"},
              lambda s, u, f: s.sales_summary(u, *f["range"], "day")),
    "weekly": ("Sales", "Weekly sales", False, {"range"},
               lambda s, u, f: s.sales_summary(u, *f["range"], "week")),
    "monthly": ("Sales", "Monthly sales", False, {"range"},
                lambda s, u, f: s.sales_summary(u, *f["range"], "month")),
    "register": ("Sales", "Sales register", False, {"range", "customer", "method"},
                 lambda s, u, f: s.sales_register(u, *f["range"], f["customer"], f["method"])),
    "product": ("Sales", "Product-wise sales", False, {"range", "category"},
                lambda s, u, f: s.product_sales(u, *f["range"], f["category"])),
    "category": ("Sales", "Category-wise sales", False, {"range"},
                 lambda s, u, f: s.category_sales(u, *f["range"])),
    "methods": ("Sales", "Payment-method sales", False, {"range"},
                lambda s, u, f: s.payment_method_sales(u, *f["range"])),
    "tax": ("Sales", "Tax summary", False, {"range"},
            lambda s, u, f: s.tax_summary(u, *f["range"])),
    "stock": ("Inventory", "Current stock", False, {"category"},
              lambda s, u, f: s.current_stock(u, f["category"])),
    "low": ("Inventory", "Low-stock items", False, {"category"},
            lambda s, u, f: s.current_stock(u, f["category"], low_only=True)),
    "movement": ("Inventory", "Stock movement", False, {"range", "mtype"},
                 lambda s, u, f: s.stock_movement(u, *f["range"], None, f["mtype"])),
    "valuation": ("Inventory", "Inventory valuation", False, {"category"},
                  lambda s, u, f: s.inventory_valuation(u, f["category"])),
    "p_register": ("Purchases", "Purchase register", False, {"range", "supplier"},
                   lambda s, u, f: s.purchase_register(u, *f["range"], f["supplier"])),
    "p_supplier": ("Purchases", "Supplier-wise purchases", False, {"range"},
                   lambda s, u, f: s.supplier_purchases(u, *f["range"])),
    "p_product": ("Purchases", "Product-wise purchases", False, {"range", "supplier"},
                  lambda s, u, f: s.product_purchases(u, *f["range"], f["supplier"])),
    "e_register": ("Expenses", "Expense register", False, {"range", "ecategory"},
                   lambda s, u, f: s.expense_register(u, *f["range"], f["ecategory"])),
    "e_category": ("Expenses", "Category-wise expenses", False, {"range"},
                   lambda s, u, f: s.expense_by_category(u, *f["range"])),
    "pl": ("Financial", "Profit & loss", True, {"range"},
           lambda s, u, f: s.profit_loss(u, *f["range"])),
    "revenue": ("Financial", "Revenue, purchases & expenses", True, {"range"},
                lambda s, u, f: s.revenue_summary(u, *f["range"])),
    "pay_summary": ("Financial", "Payment-method summary", True, {"range"},
                    lambda s, u, f: s.payment_summary(u, *f["range"])),
}


class ReportsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.report: ReportResult | None = None
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(240)
        groups = {}
        for key, (group, title, fin, _, _) in R.items():
            if fin and not ctx.can(Perm.VIEW_FINANCIAL_REPORTS):
                continue
            if not fin and not ctx.can(Perm.VIEW_REPORTS):
                continue
            if group == "Expenses" and not ctx.can(Perm.VIEW_EXPENSES):
                continue
            if group not in groups:
                g = QTreeWidgetItem([group])
                g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                self.tree.addTopLevelItem(g)
                groups[group] = g
            it = QTreeWidgetItem([title])
            it.setData(0, Qt.UserRole, key)
            groups[group].addChild(it)
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(lambda *_: self._select())
        split.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        rl.setSpacing(10)
        head = QHBoxLayout()
        self.title = label("Select a report", "SectionTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(button("Run", "primary", self.run))
        if ctx.can(Perm.EXPORT_REPORTS):
            head.addWidget(button("Export CSV", None, lambda: self.export("csv")))
            head.addWidget(button("Export PDF", None, lambda: self.export("pdf")))
        rl.addLayout(head)
        fb = QHBoxLayout()
        self.range = DateRangeBar("this_month")
        self.range.changed.connect(self.run)
        self.f = {}
        self.f["category"] = QComboBox()
        self.f["supplier"] = QComboBox()
        self.f["customer"] = QComboBox()
        self.f["method"] = QComboBox()
        self.f["ecategory"] = QComboBox()
        self.f["mtype"] = QComboBox()
        fb.addWidget(self.range)
        for w in self.f.values():
            w.currentIndexChanged.connect(self.run)
            w.setMinimumWidth(170)
            w.hide()
            fb.addWidget(w)
        fb.addStretch(1)
        rl.addLayout(fb)
        self.summary = Card(padding=12, spacing=4)
        self.summary.hide()
        rl.addWidget(self.summary)
        self.holder = QVBoxLayout()
        rl.addLayout(self.holder, 1)
        self.table = DataTable([])
        self.holder.addWidget(self.table)
        self.notes = label("", "Faint", wrap=True)
        rl.addWidget(self.notes)
        split.addWidget(right)
        self.root.addWidget(split, 1)
        self._filters_loaded = False

    def _load_filters(self):
        s = self.ctx.services
        u = self.ctx.user

        def fill(combo, first, items):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first, None)
            for text, data in items:
                combo.addItem(text, data)
            combo.blockSignals(False)
        fill(self.f["category"], "All categories",
             [(c["name"], c["id"]) for c in s.catalog.list_categories(include_inactive=True)])
        sup = s.partners.list_suppliers(u, include_inactive=True) \
            if self.ctx.can(Perm.VIEW_SUPPLIERS) else []
        fill(self.f["supplier"], "All suppliers", [(x["name"], x["id"]) for x in sup])
        cus = s.partners.list_customers(u, include_inactive=True) \
            if self.ctx.can(Perm.VIEW_CUSTOMERS) else []
        fill(self.f["customer"], "All customers", [(x["name"], x["id"]) for x in cus])
        fill(self.f["method"], "All payment methods",
             [(m["name"], m["id"]) for m in s.payment_methods.list(include_inactive=True)])
        fill(self.f["ecategory"], "All expense categories",
             [(c["name"], c["id"]) for c in s.expenses.list_categories(include_inactive=True)])
        fill(self.f["mtype"], "All movement types", list(
            (v, k) for k, v in MOVEMENT_TYPE_LABELS.items()))
        self._filters_loaded = True

    def on_show(self):
        self._load_filters()
        if self._key() is None:
            first = self.tree.topLevelItem(0)
            if first and first.childCount():
                self.tree.setCurrentItem(first.child(0))
        else:
            self.run()

    def _key(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _select(self):
        key = self._key()
        if not key:
            return
        _, title, _, filters, _ = R[key]
        self.title.setText(title)
        self.range.setVisible("range" in filters)
        for name, w in self.f.items():
            w.setVisible(name in filters)
        self.run()

    @ui_action
    def run(self):
        key = self._key()
        if not key or not self._filters_loaded:
            return
        _, _, _, filters, fn = R[key]
        f = {"range": self.range.range()}
        for name, w in self.f.items():
            f[name] = w.currentData() if name in filters else None
        rep: ReportResult = fn(self.ctx.services.reports, self.ctx.user, f)
        rep.subtitle = self.range.description() if "range" in filters else "As of now"
        self.report = rep
        clear_layout(self.holder)
        self.table = DataTable(rep.columns, stretch=rep.columns[0].key if len(rep.columns) < 4
                               else None)
        self.table.set_rows(rep.rows, totals=rep.totals)
        self.holder.addWidget(self.table)
        clear_layout(self.summary.lay)
        if rep.summary:
            for lbl, val in rep.summary:
                self.summary.lay.addWidget(QLabel(
                    f"{lbl}: <b>{val if isinstance(val, str) else self.ctx.money(val)}</b>"))
            self.summary.show()
        else:
            self.summary.hide()
        self.notes.setText("\n".join("• " + n for n in rep.notes))

    @ui_action
    def export(self, kind: str):
        if not self.report:
            show_info(self, "Run a report first.")
            return
        name = f"{self.report.title} {self.report.subtitle}".replace(" ", "_").replace("/", "-")
        default = self.ctx.export_path("reports", f"{name}.{kind}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export report", str(default),
            "CSV files (*.csv)" if kind == "csv" else "PDF files (*.pdf)")
        if not path:
            return
        if kind == "csv":
            export_csv(self.report, Path(path))
        else:
            export_pdf(self.report, Path(path), self.ctx.settings.get("business_name") or "")
        self.ctx.toast(f"Exported {Path(path).name}")
        self.ctx.open_file(Path(path))
