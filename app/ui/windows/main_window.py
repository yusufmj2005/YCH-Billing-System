"""Main application window: permission-aware sidebar + lazily created pages."""
from __future__ import annotations

import importlib
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QPushButton, QScrollArea, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from app.config.constants import APP_NAME, APP_VERSION, Perm
from app.ui.context import AppContext
from app.ui.widgets.common import Toast, handle_exception, label

log = logging.getLogger(__name__)

# section -> [(key, title, any-of permissions, "module:Class", description)]
NAVIGATION = [
    ("", [
        ("dashboard", "Dashboard", [Perm.VIEW_DASHBOARD], "dashboard:DashboardPage",
         "Business overview from recorded transactions"),
    ]),
    ("SALES", [
        ("pos", "POS / Billing", [Perm.CREATE_SALE], "pos:PosPage",
         "Scan or search products, then check out  •  F2 search  •  F12 checkout"),
        ("sales", "Sales", [Perm.VIEW_SALES], "sales:SalesPage",
         "All sales, with filters, details and controlled voiding"),
        ("invoices", "Invoices", [Perm.VIEW_SALES], "sales:InvoicesPage",
         "Find, preview, print or save invoices"),
        ("returns", "Returns", [Perm.PROCESS_RETURN], "returns:ReturnsPage",
         "Returns against original invoices, with refunds"),
    ]),
    ("CATALOG", [
        ("products", "Products", [Perm.VIEW_PRODUCTS], "products:ProductsPage",
         "Product catalogue, prices, barcodes and labels"),
        ("categories", "Categories", [Perm.MANAGE_CATEGORIES], "categories:CategoriesPage",
         "Product categories"),
        ("inventory", "Inventory", [Perm.VIEW_INVENTORY], "inventory:InventoryPage",
         "Stock levels, adjustments and the stock movement ledger"),
    ]),
    ("PURCHASING", [
        ("purchases", "Purchases", [Perm.VIEW_PURCHASES], "purchases:PurchasesPage",
         "Purchases from suppliers; completed purchases add stock"),
        ("suppliers", "Suppliers", [Perm.VIEW_SUPPLIERS], "suppliers:SuppliersPage",
         "Supplier records and purchase history"),
    ]),
    ("BUSINESS", [
        ("customers", "Customers", [Perm.VIEW_CUSTOMERS], "customers:CustomersPage",
         "Customer records and purchase history"),
        ("expenses", "Expenses", [Perm.VIEW_EXPENSES], "expenses:ExpensesPage",
         "Business expenses"),
        ("reports", "Reports", [Perm.VIEW_REPORTS, Perm.VIEW_FINANCIAL_REPORTS],
         "reports:ReportsPage", "Sales, inventory, purchase, expense and financial reports"),
    ]),
    ("STAFF", [
        ("employees", "Employees", [Perm.MANAGE_EMPLOYEES], "staff:EmployeesPage",
         "Employee records"),
        ("attendance", "Attendance", [Perm.MANAGE_ATTENDANCE], "staff:AttendancePage",
         "Daily attendance"),
        ("leave", "Leave", [Perm.MANAGE_LEAVE, Perm.APPROVE_LEAVE], "staff:LeavePage",
         "Leave requests and approvals"),
        ("payroll", "Payroll", [Perm.MANAGE_PAYROLL], "staff:PayrollPage",
         "Internal Payroll Management (no statutory calculations)"),
    ]),
    ("ADMINISTRATION", [
        ("users", "Users & Permissions", [Perm.MANAGE_USERS, Perm.MANAGE_ROLES],
         "users:UsersPage", "User accounts, roles and permissions"),
        ("settings", "Settings", [Perm.MANAGE_SETTINGS], "settings_page:SettingsPage",
         "Business, billing, tax, inventory and payment settings"),
        ("backup", "Backup & Restore", [Perm.BACKUP_DATABASE, Perm.RESTORE_DATABASE],
         "backup_page:BackupPage", "Protect your data with regular backups"),
        ("audit", "Audit Log", [Perm.VIEW_AUDIT_LOG], "audit:AuditPage",
         "Read-only record of important actions"),
    ]),
]


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        ctx.toast = self.toast
        ctx.navigate = self.navigate
        self.setWindowTitle(f"{ctx.settings.get('business_name') or APP_NAME} — {APP_NAME}")
        self.resize(1360, 820)
        self.setMinimumSize(1100, 680)
        self.pages: dict[str, QWidget] = {}
        self.page_index: dict[str, int] = {}
        self.meta: dict[str, tuple] = {}

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        row.addLayout(right, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            f"Signed in as {ctx.user.display_name} ({ctx.user.role_name})")
        self._toast = Toast(self)
        QShortcut(QKeySequence("F9"), self, activated=lambda: self.navigate("pos"))

        first = self._first_allowed()
        if first:
            self.navigate(first)

    # ---- layout ------------------------------------------------------------------
    def _allowed(self, perms) -> bool:
        return any(self.ctx.user.has(p) for p in perms)

    def _first_allowed(self) -> str | None:
        for _, items in NAVIGATION:
            for key, _, perms, _, _ in items:
                if self._allowed(perms):
                    return key
        return None

    def _build_sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(232)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        brand = QVBoxLayout()
        brand.setContentsMargins(18, 18, 18, 14)
        name = label(self.ctx.settings.get("business_name") or APP_NAME, "Brand", wrap=True)
        brand.addWidget(name)
        brand.addWidget(label(f"{APP_NAME} {APP_VERSION}", "BrandSub"))
        lay.addLayout(brand)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        nav = QVBoxLayout(inner)
        nav.setContentsMargins(0, 0, 0, 12)
        nav.setSpacing(0)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for section, items in NAVIGATION:
            visible = [it for it in items if self._allowed(it[2])]
            if not visible:
                continue
            if section:
                nav.addWidget(label(section, "NavHeading"))
            for key, title, perms, target, desc in visible:
                b = QPushButton(title)
                b.setObjectName("NavButton")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self.navigate(k))
                self.nav_group.addButton(b)
                self.nav_buttons[key] = b
                self.meta[key] = (title, target, desc)
                nav.addWidget(b)
        nav.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        return frame

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 12, 18, 12)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = label("", "PageTitle")
        self.subtitle = label("", "Muted")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        lay.addLayout(titles, 1)
        user_btn = QToolButton()
        user_btn.setText(f"{self.ctx.user.display_name}  ▾")
        user_btn.setToolTip(self.ctx.user.role_name)
        user_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(user_btn)
        info = QAction(f"{self.ctx.user.username} — {self.ctx.user.role_name}", menu)
        info.setEnabled(False)
        menu.addAction(info)
        menu.addSeparator()
        menu.addAction("Change password…", self._change_password)
        menu.addAction("Sign out", self.logout_requested.emit)
        user_btn.setMenu(menu)
        lay.addWidget(user_btn)
        return bar

    # ---- navigation ----------------------------------------------------------------
    def navigate(self, key: str) -> None:
        if key not in self.meta:
            return
        title, target, desc = self.meta[key]
        try:
            if key not in self.pages:
                mod_name, cls_name = target.split(":")
                mod = importlib.import_module(f"app.ui.pages.{mod_name}")
                page = getattr(mod, cls_name)(self.ctx)
                self.pages[key] = page
                self.page_index[key] = self.stack.addWidget(page)
            page = self.pages[key]
            self.stack.setCurrentIndex(self.page_index[key])
            self.nav_buttons[key].setChecked(True)
            self.title.setText(title)
            self.subtitle.setText(desc)
            page.on_show()
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)

    def toast(self, message: str) -> None:
        self._toast.show_message(message)
        self.statusBar().showMessage(message, 5000)

    def _change_password(self) -> None:
        from app.ui.dialogs.password_dialogs import ChangePasswordDialog
        if ChangePasswordDialog(self, self.ctx.services, self.ctx.user).exec():
            self.toast("Password changed")
