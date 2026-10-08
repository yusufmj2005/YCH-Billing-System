from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from app.config.constants import TAX_MODE_LABELS, Perm
from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import Card, button, confirm, handle_exception, label, ui_action
from app.ui.widgets.forms import Field, FormDialog, decimal_edit
from app.ui.widgets.table import DataTable


def _form_tab(tabs: QTabWidget, title: str) -> tuple[QFormLayout, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    inner = QWidget()
    inner.setObjectName("Page")
    v = QVBoxLayout(inner)
    v.setContentsMargins(0, 12, 0, 0)
    card = Card(padding=20)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    card.lay.addLayout(form)
    v.addWidget(card)
    v.addStretch(1)
    scroll.setWidget(inner)
    tabs.addTab(scroll, title)
    return form, card.lay


class SettingsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)

        # ---- business
        f, lay = _form_tab(self.tabs, "Business")
        self.b_name = QLineEdit()
        self.b_address = QPlainTextEdit()
        self.b_address.setFixedHeight(64)
        self.b_phone = QLineEdit()
        self.b_email = QLineEdit()
        self.b_gstin = QLineEdit()
        self.b_gstin.setMaxLength(15)
        self.b_state = QLineEdit()
        self.b_currency = QLineEdit()
        self.b_currency.setMaxLength(4)
        self.b_currency.setMaximumWidth(80)
        logo_row = QHBoxLayout()
        self.logo_lbl = QLabel()
        logo_row.addWidget(self.logo_lbl)
        logo_row.addWidget(button("Change logo…", None, self.change_logo))
        logo_row.addWidget(button("Remove logo", "ghost", self.remove_logo))
        logo_row.addStretch(1)
        for text, w in (("Business name *", self.b_name), ("Address", self.b_address),
                        ("Phone", self.b_phone), ("Email", self.b_email),
                        ("GSTIN", self.b_gstin), ("State", self.b_state),
                        ("Currency symbol", self.b_currency), ("Logo", logo_row)):
            f.addRow(text, w)
        lay.addWidget(button("Save business details", "primary", self.save_business),
                      alignment=Qt.AlignRight)

        # ---- billing
        f, lay = _form_tab(self.tabs, "Billing")
        self.i_prefix = QLineEdit()
        self.i_prefix.setMaxLength(12)
        self.i_next = QSpinBox()
        self.i_next.setRange(1, 999_999_999)
        self.i_pad = QSpinBox()
        self.i_pad.setRange(1, 10)
        self.i_title = QLineEdit()
        self.i_paper = QComboBox()
        self.i_paper.addItem("A4 page", "A4")
        self.i_paper.addItem("80 mm receipt printer", "RECEIPT_80MM")
        self.i_footer = QPlainTextEdit()
        self.i_footer.setFixedHeight(56)
        self.i_auto = QCheckBox("Print the invoice automatically after each sale "
                                "(default printer)")
        self.i_round = QCheckBox("Round the grand total to the nearest whole unit")
        self.i_taxmode = QComboBox()
        for k, text in TAX_MODE_LABELS.items():
            self.i_taxmode.addItem(text, k)
        self.r_prefix = QLineEdit()
        self.r_prefix.setMaxLength(12)
        self.p_prefix = QLineEdit()
        self.p_prefix.setMaxLength(12)
        self.max_disc = decimal_edit(None, "No limit")
        for text, w in (("Invoice prefix", self.i_prefix), ("Next invoice number", self.i_next),
                        ("Number of digits", self.i_pad), ("Invoice title", self.i_title),
                        ("Invoice paper", self.i_paper), ("Invoice footer", self.i_footer),
                        ("", self.i_auto), ("", self.i_round),
                        ("Default tax type", self.i_taxmode), ("Return number prefix", self.r_prefix),
                        ("Purchase number prefix", self.p_prefix),
                        ("Max discount % without approval", self.max_disc)):
            f.addRow(text, w)
        f.addRow("", label("Invoice numbers can only move forward; numbers already issued are "
                           "never reused. Users with 'Exceed maximum discount limit' permission "
                           "can approve larger discounts.", "Faint", wrap=True))
        lay.addWidget(button("Save billing settings", "primary", self.save_billing),
                      alignment=Qt.AlignRight)

        # ---- tax
        w = QWidget()
        tl = QVBoxLayout(w)
        tl.setContentsMargins(0, 12, 0, 0)
        tl.addWidget(label("Configure the tax / GST rates your business uses and assign them to "
                           "products. Rate changes apply to future sales only; past invoices keep "
                           "the rate recorded at the time. BusinessPOS does not determine which "
                           "rate legally applies — confirm with your tax adviser.", "Notice",
                           wrap=True))
        bar = QHBoxLayout()
        self.incl_default = QCheckBox("New products: selling price includes tax")
        self.incl_default.toggled.connect(self.save_incl_default)
        bar.addWidget(self.incl_default)
        bar.addStretch(1)
        bar.addWidget(button("Add tax rate", "primary", lambda: self.edit_tax(None)))
        bar.addWidget(button("Edit", None, lambda: self.edit_tax(self.tax_table.selected())))
        tl.addLayout(bar)
        self.tax_table = DataTable([Col("name", "Name"), Col("rate", "Rate", "pct"),
                                    Col("description", "Description"), Col("status", "Status")],
                                   stretch="description")
        self.tax_table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.tax_table.activated.connect(self.edit_tax)
        tl.addWidget(self.tax_table, 1)
        self.tabs.addTab(w, "Tax")

        # ---- inventory
        f, lay = _form_tab(self.tabs, "Inventory")
        self.low_threshold = decimal_edit(None, "0")
        self.neg_stock = QCheckBox("Allow sales when stock is insufficient (creates negative stock)")
        self.sku_unique = QCheckBox("SKU must be unique")
        self.units = QLineEdit()
        self.units.setPlaceholderText("Comma separated, e.g. pcs, ball, skein")
        self.bc_type = QComboBox()
        self.bc_type.addItem("Code 128 (letters and digits)", "CODE128")
        self.bc_type.addItem("EAN-13 (13 digits, in-store prefix 20-29)", "EAN13")
        self.bc_prefix = QLineEdit()
        self.bc_prefix.setMaxLength(12)
        for text, w2 in (("Default low-stock threshold", self.low_threshold), ("", self.neg_stock),
                         ("", self.sku_unique), ("Units of measure", self.units),
                         ("Generated barcode type", self.bc_type),
                         ("Generated barcode prefix", self.bc_prefix)):
            f.addRow(text, w2)
        f.addRow("", label("The threshold applies to products without their own minimum level. "
                           "Barcodes are only generated when a user clicks 'Generate'; "
                           "manufacturer barcodes can be scanned or typed instead.", "Faint",
                           wrap=True))
        lay.addWidget(button("Save inventory settings", "primary", self.save_inventory),
                      alignment=Qt.AlignRight)

        # ---- payments
        w = QWidget()
        pl = QVBoxLayout(w)
        pl.setContentsMargins(0, 12, 0, 0)
        pl.addWidget(label("Payment methods are for record keeping. BusinessPOS records how the "
                           "customer paid and an optional transaction / reference ID; it never "
                           "stores card numbers, CVV, PINs or bank credentials.", "Notice",
                           wrap=True))
        upi = QFormLayout()
        upi.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.upi_id = QLineEdit()
        self.upi_id.setPlaceholderText("e.g. yarnshop@okaxis  (leave blank to turn off)")
        self.upi_name = QLineEdit()
        self.upi_name.setMaxLength(50)
        self.upi_name.setPlaceholderText("Shown to the customer in their UPI app")
        upi.addRow(label("UPI QR at checkout", "SectionTitle"))
        upi.addRow("Shop UPI ID", self.upi_id)
        upi.addRow("Payee name", self.upi_name)
        upi_row = QHBoxLayout()
        upi_row.addWidget(label("Checkout shows a QR code with the exact amount; the customer "
                                "scans it with any UPI app. Money goes straight to your bank.",
                                "Faint", wrap=True), 1)
        upi_row.addWidget(button("Save UPI", "primary", self.save_upi))
        upi.addRow("", upi_row)
        upi.addRow(label("Razorpay (online payments, confirmed automatically)",
                         "SectionTitle"))
        self.rzp_status = label("", "Muted", wrap=True)
        upi.addRow("Status", self.rzp_status)
        self.rzp_key = QLineEdit()
        self.rzp_key.setPlaceholderText("rzp_live_…  (or rzp_test_… to try it first)")
        self.rzp_key.setMaxLength(60)
        self.rzp_secret = QLineEdit()
        self.rzp_secret.setEchoMode(QLineEdit.Password)
        self.rzp_secret.setMaxLength(80)
        self.rzp_secret.setPlaceholderText("Key Secret (shown once by Razorpay when the key is "
                                           "generated)")
        upi.addRow("Key ID", self.rzp_key)
        upi.addRow("Key Secret", self.rzp_secret)
        rzp_row = QHBoxLayout()
        rzp_row.addWidget(label("Razorpay Dashboard › Account & Settings › API keys. The secret "
                                "is locked to this Windows account. Razorpay charges its own "
                                "fees.", "Faint", wrap=True), 1)
        self.rzp_check = button("Check payments…", None, self.check_razorpay)
        self.rzp_disconnect = button("Disconnect", "danger", self.disconnect_razorpay)
        rzp_row.addWidget(self.rzp_check)
        rzp_row.addWidget(self.rzp_disconnect)
        rzp_row.addWidget(button("Connect", "primary", self.connect_razorpay))
        upi.addRow("", rzp_row)
        pl.addLayout(upi)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(button("Add payment method", "primary", lambda: self.edit_method(None)))
        bar.addWidget(button("Edit", None, lambda: self.edit_method(self.pm_table.selected())))
        pl.addLayout(bar)
        self.pm_table = DataTable([Col("name", "Method"), Col("kind", "Type"),
                                   Col("allows_reference", "Reference ID", "bool"),
                                   Col("requires_description", "Needs description", "bool"),
                                   Col("status", "Status")], stretch="name")
        self.pm_table.set_row_color(lambda r: None if r["is_active"] else C["faint"])
        self.pm_table.activated.connect(self.edit_method)
        pl.addWidget(self.pm_table, 1)
        self.tabs.addTab(w, "Payments")

        # ---- security & backup
        f, lay = _form_tab(self.tabs, "Security && backup")
        self.idle = QSpinBox()
        self.idle.setRange(0, 480)
        self.idle.setSuffix(" minutes")
        self.idle.setSpecialValueText("Never")
        self.auto_backup = QCheckBox("Create an automatic backup once a day when the application "
                                     "starts")
        self.keep = QSpinBox()
        self.keep.setRange(1, 1000)
        f.addRow("Sign out after inactivity", self.idle)
        self.exit_backup = QCheckBox("Also back up every time the application is closed")
        self.copy_folder = QLineEdit()
        self.copy_folder.setPlaceholderText("Optional: USB drive or OneDrive / Google Drive folder")
        copy_row = QHBoxLayout()
        copy_row.addWidget(self.copy_folder, 1)
        copy_row.addWidget(button("Choose…", None, self._pick_copy_folder))
        f.addRow("", self.auto_backup)
        f.addRow("", self.exit_backup)
        f.addRow("Automatic backups to keep", self.keep)
        f.addRow("Second copy folder", copy_row)
        f.addRow("", label("Each automatic backup is also copied here, so your data survives if "
                           "this computer fails or is stolen. You are warned at start-up if the "
                           "folder is not available.", "Faint", wrap=True))
        self.enc_status = label("", "SectionTitle")
        enc_row = QHBoxLayout()
        enc_row.addWidget(self.enc_status, 1)
        enc_row.addWidget(button("Set backup password…", None, self.set_backup_password))
        self.enc_remove = button("Remove", "ghost", self.remove_backup_password)
        enc_row.addWidget(self.enc_remove)
        f.addRow("Backup password", enc_row)
        f.addRow("", label("Encrypts every backup, including copies on USB or cloud folders. "
                           "Restoring on another computer asks for this password. If the "
                           "password is forgotten, encrypted backups CANNOT be restored, so "
                           "write it down and keep it safe.", "Faint", wrap=True))
        f.addRow("", label("Users, roles and permissions are managed on the Users & Permissions "
                           "page.", "Faint"))
        if ctx.can(Perm.MANAGE_USERS) or ctx.can(Perm.MANAGE_ROLES):
            f.addRow("", button("Open Users && Permissions", "ghost",
                                lambda: ctx.navigate("users")))
        lay.addWidget(button("Save", "primary", self.save_security), alignment=Qt.AlignRight)

    # ---- load -------------------------------------------------------------------------
    def on_show(self):
        self.ctx.reload_settings()
        s = self.ctx.settings
        self.b_name.setText(s.get("business_name", ""))
        self.b_address.setPlainText(s.get("business_address", ""))
        self.b_phone.setText(s.get("business_phone", ""))
        self.b_email.setText(s.get("business_email", ""))
        self.b_gstin.setText(s.get("business_gstin", ""))
        self.b_state.setText(s.get("business_state", ""))
        self.b_currency.setText(s.get("currency_symbol", ""))
        self._show_logo()
        self.i_prefix.setText(s.get("invoice_prefix", ""))
        self.i_next.setValue(int(s.get("next_invoice_number", 1)))
        self.i_pad.setValue(int(s.get("invoice_padding", 6)))
        self.i_title.setText(s.get("invoice_title", ""))
        self.i_paper.setCurrentIndex(max(0, self.i_paper.findData(s.get("invoice_paper"))))
        self.i_footer.setPlainText(s.get("invoice_footer", ""))
        self.i_auto.setChecked(bool(s.get("auto_print_invoice")))
        self.i_round.setChecked(bool(s.get("round_off_total")))
        self.i_taxmode.setCurrentIndex(max(0, self.i_taxmode.findData(s.get("default_tax_mode"))))
        self.r_prefix.setText(s.get("return_prefix", ""))
        self.p_prefix.setText(s.get("purchase_prefix", ""))
        self.max_disc.setText(str(s.get("max_discount_percent") or ""))
        self.incl_default.blockSignals(True)
        self.incl_default.setChecked(bool(s.get("default_price_includes_tax", True)))
        self.incl_default.blockSignals(False)
        self.low_threshold.setText(str(s.get("low_stock_threshold") or "0"))
        self.neg_stock.setChecked(bool(s.get("allow_negative_stock")))
        self.sku_unique.setChecked(bool(s.get("sku_unique", True)))
        self.units.setText(", ".join(s.get("units") or []))
        self.bc_type.setCurrentIndex(max(0, self.bc_type.findData(s.get("barcode_symbology"))))
        self.bc_prefix.setText(s.get("barcode_prefix", ""))
        self.idle.setValue(int(s.get("idle_logout_minutes", 0)))
        self.auto_backup.setChecked(bool(s.get("auto_backup_on_start", True)))
        self.keep.setValue(int(s.get("backup_keep_count", 30)))
        self.exit_backup.setChecked(bool(s.get("backup_on_exit", True)))
        self.upi_id.setText(s.get("upi_id", ""))
        self.upi_name.setText(s.get("upi_payee_name", "") or "")
        self._show_razorpay()
        self.copy_folder.setText(s.get("backup_copy_folder", ""))
        enc = self.ctx.services.backup.encryption_enabled()
        self.enc_status.setText("On: backups are encrypted" if enc else "Off")
        self.enc_remove.setVisible(enc)
        self.load_tax()
        self.load_methods()

    def _show_logo(self):
        f = self.ctx.services.settings.logo_file()
        if f:
            pm = QPixmap(str(f))
            self.logo_lbl.setPixmap(pm.scaledToHeight(40, Qt.SmoothTransformation))
        else:
            self.logo_lbl.setText("No logo")

    def _save(self, changes: dict, message: str = "Settings saved"):
        self.ctx.services.settings.update(self.ctx.user, changes)
        self.ctx.reload_settings()
        self.ctx.toast(message)
        self.on_show()

    # ---- savers ---------------------------------------------------------------------
    @ui_action
    def save_business(self):
        self._save({"business_name": self.b_name.text(),
                    "business_address": self.b_address.toPlainText(),
                    "business_phone": self.b_phone.text(), "business_email": self.b_email.text(),
                    "business_gstin": self.b_gstin.text(), "business_state": self.b_state.text(),
                    "currency_symbol": self.b_currency.text()},
                   "Business details saved (window title updates at next sign-in)")

    @ui_action
    def change_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo", "", "Images (*.png *.jpg *.jpeg)")
        if path:
            name = self.ctx.services.settings.store_logo(self.ctx.user, path)
            self._save({"logo_path": name}, "Logo updated")

    @ui_action
    def remove_logo(self):
        self._save({"logo_path": ""}, "Logo removed")

    @ui_action
    def save_billing(self):
        self._save({"invoice_prefix": self.i_prefix.text(),
                    "next_invoice_number": self.i_next.value(),
                    "invoice_padding": self.i_pad.value(), "invoice_title": self.i_title.text(),
                    "invoice_paper": self.i_paper.currentData(),
                    "invoice_footer": self.i_footer.toPlainText(),
                    "auto_print_invoice": self.i_auto.isChecked(),
                    "round_off_total": self.i_round.isChecked(),
                    "default_tax_mode": self.i_taxmode.currentData(),
                    "return_prefix": self.r_prefix.text(),
                    "purchase_prefix": self.p_prefix.text(),
                    "max_discount_percent": self.max_disc.text()})

    @ui_action
    def save_incl_default(self, checked: bool):
        self._save({"default_price_includes_tax": checked})

    @ui_action
    def save_inventory(self):
        self._save({"low_stock_threshold": self.low_threshold.text() or "0",
                    "allow_negative_stock": self.neg_stock.isChecked(),
                    "sku_unique": self.sku_unique.isChecked(),
                    "units": [u.strip() for u in self.units.text().split(",")],
                    "barcode_symbology": self.bc_type.currentData(),
                    "barcode_prefix": self.bc_prefix.text()})

    @ui_action
    def save_security(self):
        self._save({"idle_logout_minutes": self.idle.value(),
                    "auto_backup_on_start": self.auto_backup.isChecked(),
                    "backup_on_exit": self.exit_backup.isChecked(),
                    "backup_keep_count": self.keep.value(),
                    "backup_copy_folder": self.copy_folder.text()},
                   "Saved (auto sign-out applies from the next sign-in)")

    @ui_action
    def set_backup_password(self):
        from app.ui.widgets.forms import Field, FormDialog
        svc = self.ctx.services.backup
        dlg = FormDialog(self, "Backup password", [
            Field("password", "New backup password", "password", required=True),
            Field("confirm", "Confirm password", "password", required=True)],
            on_submit=lambda d: svc.set_backup_password(self.ctx.user, d["password"],
                                                        d["confirm"]),
            intro="From now on every backup is encrypted with this password. Backups made "
                  "earlier keep their current protection. Keep the password safe: it cannot "
                  "be recovered.", submit_text="Set password")
        if dlg.exec():
            self.ctx.toast("Backup password set; new backups are encrypted")
            self.on_show()

    @ui_action
    def remove_backup_password(self):
        if confirm(self, "Stop encrypting new backups?\n\nBackups already encrypted still "
                         "need the password to restore.", danger=True, yes_text="Remove"):
            self.ctx.services.backup.remove_backup_password(self.ctx.user)
            self.ctx.toast("Backup password removed")
            self.on_show()

    @ui_action
    def save_upi(self):
        self._save({"upi_id": self.upi_id.text(), "upi_payee_name": self.upi_name.text()},
                   "UPI settings saved")

    def _show_razorpay(self):
        st = self.ctx.services.razorpay.status()
        if st["connected"]:
            mode = "TEST mode (no real money)" if st["mode"] == "test" else "Live"
            text = f"Connected: {mode}, key {st['key_id']}. Checkout shows a Razorpay button."
        elif st["needs_secret"]:
            text = (f"Key {st['key_id']} is saved but its secret can't be read on this "
                    "computer / Windows account. Enter the Key Secret again and Connect.")
        else:
            text = "Not connected."
        self.rzp_status.setText(text)
        if st["key_id"] and not self.rzp_key.text():
            self.rzp_key.setText(st["key_id"])
        self.rzp_disconnect.setVisible(bool(st["key_id"]))
        self.rzp_check.setVisible(st["connected"])

    def connect_razorpay(self):
        from app.ui.dialogs.razorpay_dialog import busy
        try:
            with busy():
                st = self.ctx.services.razorpay.connect(self.ctx.user, self.rzp_key.text(),
                                                         self.rzp_secret.text())
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.rzp_secret.clear()
        self.ctx.reload_settings()
        self.ctx.toast("Razorpay connected" + (" in TEST mode" if st["mode"] == "test" else ""))
        self.on_show()

    def disconnect_razorpay(self):
        if not confirm(self, "Disconnect Razorpay? The saved keys are removed from this "
                             "computer and the Razorpay button disappears from checkout. Past "
                             "sales are not changed.", danger=True, yes_text="Disconnect"):
            return
        try:
            self.ctx.services.razorpay.disconnect(self.ctx.user)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.rzp_key.clear()
        self.rzp_secret.clear()
        self.ctx.toast("Razorpay disconnected")
        self.on_show()

    def check_razorpay(self):
        from app.ui.dialogs.razorpay_check_dialog import RazorpayCheckDialog
        dlg = RazorpayCheckDialog(self, self.ctx)
        if dlg.load():
            dlg.exec()

    def _pick_copy_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the second backup folder",
                                                  self.copy_folder.text())
        if folder:
            self.copy_folder.setText(folder)

    # ---- tax rates / payment methods ---------------------------------------------------
    @ui_action
    def load_tax(self):
        rows = self.ctx.services.catalog.list_tax_rates(include_inactive=True)
        for r in rows:
            r["status"] = "Active" if r["is_active"] else "Inactive"
        self.tax_table.set_rows(rows)

    def edit_tax(self, row):
        vals = dict(row) if row else {"is_active": True}
        if row:
            vals["rate"] = f"{row['rate'].normalize():f}"
        if FormDialog(self, "Tax rate", [
                Field("name", "Name", required=True, max_length=64,
                      placeholder="e.g. GST 5%"),
                Field("rate", "Rate (%)", "decimal", required=True),
                Field("description", "Description"), Field("is_active", "Active", "check")],
                vals, lambda d: self.ctx.services.catalog.save_tax_rate(
                    self.ctx.user, row["id"] if row else None, d),
                intro="Changing a rate affects future sales only.").exec():
            self.load_tax()

    @ui_action
    def load_methods(self):
        rows = self.ctx.services.payment_methods.list(include_inactive=True)
        for r in rows:
            r["status"] = "Enabled" if r["is_active"] else "Disabled"
        self.pm_table.set_rows(rows)

    def edit_method(self, row):
        fields = [Field("name", "Name", required=True, max_length=64),
                  Field("allows_reference", "Record transaction / reference ID", "check"),
                  Field("requires_description", "Ask for a description of the method", "check"),
                  Field("is_active", "Enabled", "check")]
        if row and row["kind"] == "CASH":
            fields = [fields[0], fields[3]]
        if FormDialog(self, "Payment method", fields,
                      row or {"is_active": True, "allows_reference": True},
                      lambda d: self.ctx.services.payment_methods.save(
                          self.ctx.user, row["id"] if row else None, d)).exec():
            self.load_methods()
