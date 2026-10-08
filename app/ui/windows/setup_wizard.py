"""First-run setup wizard: business details, administrator, billing, tax rates,
payment methods. Nothing is pre-filled with business information."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage)

from app.bootstrap import Services
from app.config.constants import APP_NAME, DEFAULT_PAYMENT_METHODS, TAX_MODE_LABELS, TaxMode
from app.security.passwords import validate_password_strength
from app.services.auth_service import validate_username
from app.services.errors import BusinessError
from app.services.settings_service import format_doc_no
from app.ui.dialogs.password_dialogs import PASSWORD_HELP
from app.ui.widgets.common import button, handle_exception, label, show_error
from app.ui.widgets.forms import decimal_edit
from app.validators import common as v

log = logging.getLogger(__name__)


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(10)
    return f


def _set_form(page: QWizardPage, form: QFormLayout) -> None:
    """Top-align the form so extra height goes below it, not between rows."""
    outer = QVBoxLayout(page)
    outer.addLayout(form)
    outer.addStretch(1)


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle(f"Welcome to {APP_NAME}")
        self.setSubTitle("Let's set up your business. This takes about two minutes.")
        lay = QVBoxLayout(self)
        lay.addWidget(label(
            "You will enter:\n\n"
            "  1.  Your business details (printed on invoices)\n"
            "  2.  An administrator account for signing in\n"
            "  3.  Invoice numbering\n"
            "  4.  The tax rates your business uses\n"
            "  5.  Accepted payment methods\n\n"
            "Everything can be changed later in Settings. Your data is stored only on this "
            "computer; use Backup & Restore to keep copies elsewhere.", wrap=True))
        lay.addStretch(1)


class BusinessPage(QWizardPage):
    def __init__(self, wizard: "SetupWizard"):
        super().__init__()
        self.wiz = wizard
        self.setTitle("Business details")
        self.setSubTitle("Shown on invoices and reports. Only the business name is required.")
        f = _form()
        self.name = QLineEdit()
        self.address = QPlainTextEdit()
        self.address.setFixedHeight(64)
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.gstin = QLineEdit()
        self.gstin.setPlaceholderText("Leave blank if not registered")
        self.gstin.setMaxLength(15)
        self.state = QLineEdit()
        self.state.setPlaceholderText("State / place of business (optional)")
        f.addRow("Business name *", self.name)
        f.addRow("Address", self.address)
        f.addRow("Phone", self.phone)
        f.addRow("Email", self.email)
        f.addRow("GSTIN", self.gstin)
        f.addRow("State", self.state)
        logo_row = QHBoxLayout()
        self.logo_preview = QLabel("No logo")
        self.logo_preview.setObjectName("Faint")
        self.logo_path = ""
        logo_row.addWidget(button("Choose logo…", None, self._pick_logo))
        logo_row.addWidget(button("Remove", "ghost", self._clear_logo))
        logo_row.addWidget(self.logo_preview, 1)
        f.addRow("Logo", logo_row)
        _set_form(self, f)

    def _pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            pm = QPixmap(path)
            if pm.isNull():
                show_error(self, "That image could not be opened.")
                return
            self.logo_path = path
            self.logo_preview.setPixmap(pm.scaledToHeight(40, Qt.SmoothTransformation))

    def _clear_logo(self):
        self.logo_path = ""
        self.logo_preview.setText("No logo")

    def validatePage(self) -> bool:
        try:
            v.text(self.name.text(), "Business name", required=True, max_len=150)
            v.phone(self.phone.text())
            v.email(self.email.text())
            v.gstin(self.gstin.text())
        except BusinessError as exc:
            show_error(self, str(exc))
            return False
        return True


class AdminPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Administrator account")
        self.setSubTitle("This account has full access. Choose a strong password and keep it "
                         "safe - it cannot be recovered without another administrator.")
        f = _form()
        self.full_name = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        f.addRow("Full name", self.full_name)
        f.addRow("Username *", self.username)
        f.addRow("Password *", self.password)
        f.addRow("", label(PASSWORD_HELP, "Faint", wrap=True))
        f.addRow("Confirm password *", self.confirm)
        _set_form(self, f)

    def validatePage(self) -> bool:
        try:
            u = validate_username(self.username.text())
            if self.password.text() != self.confirm.text():
                raise BusinessError("Passwords do not match.")
            validate_password_strength(self.password.text(), u)
        except BusinessError as exc:
            show_error(self, str(exc))
            return False
        return True


class BillingPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Invoices")
        self.setSubTitle("Invoice numbers are unique and never reused.")
        f = _form()
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("e.g. INV-  (letters, digits, / - _ ; may be blank)")
        self.prefix.setMaxLength(12)
        self.start = QSpinBox()
        self.start.setRange(1, 999_999_999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 10)
        self.digits.setValue(6)
        self.preview = label("", "Muted")
        self.title = QLineEdit("Invoice")
        self.paper = QComboBox()
        self.paper.addItem("A4 page", "A4")
        self.paper.addItem("80 mm receipt printer", "RECEIPT_80MM")
        self.footer = QLineEdit()
        self.footer.setPlaceholderText("Optional, e.g. return policy or thank-you note")
        self.tax_mode = QComboBox()
        for k, text in TAX_MODE_LABELS.items():
            self.tax_mode.addItem(text, k)
        self.incl = QCheckBox("Product selling prices include tax (default for new products)")
        self.incl.setChecked(True)
        f.addRow("Invoice prefix", self.prefix)
        f.addRow("Starting number", self.start)
        f.addRow("Number of digits", self.digits)
        f.addRow("First invoice", self.preview)
        f.addRow("Invoice title", self.title)
        f.addRow("Invoice paper", self.paper)
        f.addRow("Invoice footer", self.footer)
        f.addRow("Default tax type", self.tax_mode)
        f.addRow("", self.incl)
        _set_form(self, f)
        for w in (self.prefix,):
            w.textChanged.connect(self._update)
        self.start.valueChanged.connect(self._update)
        self.digits.valueChanged.connect(self._update)
        self._update()

    def _update(self):
        self.preview.setText(format_doc_no(self.prefix.text().strip(), self.start.value(),
                                           self.digits.value()))

    def validatePage(self) -> bool:
        import re
        if not re.fullmatch(r"[A-Za-z0-9/_\-]{0,12}", self.prefix.text().strip()):
            show_error(self, "The prefix may contain only letters, digits, '/', '-' or '_'.")
            return False
        if not self.title.text().strip():
            show_error(self, "Please enter an invoice title.")
            return False
        return True


class TaxPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Tax rates")
        self.setSubTitle("Add each tax / GST rate your business uses. BusinessPOS does not "
                         "decide which rate applies to a product - confirm rates with your "
                         "tax adviser. You can skip this and add rates later in Settings.")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name, e.g. GST 5%")
        self.rate = decimal_edit(None, "Rate %")
        self.rate.setMaximumWidth(110)
        row.addWidget(self.name, 1)
        row.addWidget(self.rate)
        row.addWidget(button("Add", "primary", self._add))
        lay.addLayout(row)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Rate (%)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)
        lay.addWidget(button("Remove selected", "danger", self._remove))
        self.rates: list[dict] = []
        self.rate.returnPressed.connect(self._add)

    def _add(self):
        try:
            name = v.text(self.name.text(), "Tax name", required=True, max_len=64)
            rate = v.percent(self.rate.text(), "Tax rate")
            if any(r["name"].lower() == name.lower() for r in self.rates):
                raise BusinessError("A tax rate with this name was already added.")
        except BusinessError as exc:
            show_error(self, str(exc))
            return
        self.rates.append({"name": name, "rate": str(rate)})
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        it = QTableWidgetItem(f"{rate.normalize():f}")
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(r, 1, it)
        self.name.clear()
        self.rate.clear()
        self.name.setFocus()

    def _remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self.rates.pop(r)

    def validatePage(self) -> bool:
        # A rate typed but not yet added must not be silently dropped.
        if self.name.text().strip() or self.rate.text().strip():
            before = len(self.rates)
            self._add()
            return len(self.rates) > before
        return True


class PaymentPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Payment methods")
        self.setSubTitle("Choose the payment methods you accept. BusinessPOS records how a "
                         "customer paid; it does not process card or UPI payments.")
        lay = QVBoxLayout(self)
        self.checks = {}
        for kind, name, _, _ in DEFAULT_PAYMENT_METHODS:
            c = QCheckBox(name)
            c.setChecked(True)
            self.checks[kind] = c
            lay.addWidget(c)
        lay.addWidget(label("You can rename methods or add custom ones later in Settings.",
                            "Faint"))
        lay.addStretch(1)

    def validatePage(self) -> bool:
        if not any(c.isChecked() for c in self.checks.values()):
            show_error(self, "Enable at least one payment method.")
            return False
        return True


class SetupWizard(QWizard):
    setup_done = Signal(object)  # CurrentUser

    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.setWindowTitle(f"{APP_NAME} — First-time setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setMinimumSize(720, 600)
        self.business = BusinessPage(self)
        self.admin = AdminPage()
        self.billing = BillingPage()
        self.tax = TaxPage()
        self.payments = PaymentPage()
        for p in (WelcomePage(), self.business, self.admin, self.billing, self.tax,
                  self.payments):
            self.addPage(p)
        self.setButtonText(QWizard.FinishButton, "Finish setup")

    def accept(self) -> None:
        b = self.business
        try:
            logo = self.services.settings.store_logo(None, b.logo_path) if b.logo_path else ""
            data = {
                "business_name": b.name.text(), "business_address": b.address.toPlainText(),
                "business_phone": b.phone.text(), "business_email": b.email.text(),
                "business_gstin": b.gstin.text(), "business_state": b.state.text(),
                "logo_path": logo,
                "admin_full_name": self.admin.full_name.text(),
                "admin_username": self.admin.username.text(),
                "admin_password": self.admin.password.text(),
                "admin_password_confirm": self.admin.confirm.text(),
                "invoice_prefix": self.billing.prefix.text().strip(),
                "invoice_start_number": self.billing.start.value(),
                "invoice_padding": self.billing.digits.value(),
                "invoice_title": self.billing.title.text().strip(),
                "invoice_paper": self.billing.paper.currentData(),
                "invoice_footer": self.billing.footer.text(),
                "default_tax_mode": self.billing.tax_mode.currentData() or TaxMode.INTRA,
                "default_price_includes_tax": self.billing.incl.isChecked(),
                "tax_rates": self.tax.rates,
                "enabled_payment_methods": [k for k, c in self.payments.checks.items()
                                            if c.isChecked()],
            }
            user = self.services.auth.complete_setup(data)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        log.info("First-time setup completed")
        self.setup_done.emit(user)  # open the main window before this one hides
        super().accept()
