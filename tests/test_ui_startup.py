"""Offscreen tests of the first screens a business sees: setup wizard and sign-in."""
from __future__ import annotations

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from app.config.constants import PaymentKind  # noqa: E402
from app.ui.styles.theme import apply_theme  # noqa: E402
from app.ui.windows.login_window import LoginWindow  # noqa: E402
from app.ui.windows.setup_wizard import SetupWizard  # noqa: E402
from tests.conftest import ADMIN_PASSWORD  # noqa: E402

GOOD_PW = "Shop-Owner-2024"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture()
def dialogs(monkeypatch):
    shown = []
    for name in ("warning", "information", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _n=name, **k: shown.append((_n, a)))
    return shown


def _fill_wizard(wiz: SetupWizard):
    b = wiz.business
    b.name.setText("Yarn & Hook Store")
    b.phone.setText("+91 98765 43210")
    b.email.setText("owner@example.com")
    b.gstin.setText("29abcde1234f1z5")
    wiz.admin.full_name.setText("Shop Owner")
    wiz.admin.username.setText("owner")
    wiz.admin.password.setText(GOOD_PW)
    wiz.admin.confirm.setText(GOOD_PW)
    wiz.billing.prefix.setText("YH-")
    wiz.billing.start.setValue(101)
    wiz.billing.digits.setValue(5)


# ---- setup wizard ------------------------------------------------------------------
def test_setup_wizard_completes_and_saves_everything(qapp, services, dialogs):
    wiz = SetupWizard(services)
    done = []
    wiz.setup_done.connect(done.append)
    _fill_wizard(wiz)
    assert wiz.billing.preview.text() == "YH-00101"
    wiz.tax.name.setText("GST 5%")
    wiz.tax.rate.setText("5")
    wiz.tax._add()
    wiz.payments.checks[PaymentKind.OTHER].setChecked(False)
    for page in (wiz.business, wiz.admin, wiz.billing, wiz.tax, wiz.payments):
        assert page.validatePage(), dialogs
    wiz.accept()
    assert dialogs == []
    assert len(done) == 1 and done[0].username == "owner" and done[0].is_admin

    s = services.settings.get_all()
    assert s["business_name"] == "Yarn & Hook Store"
    assert s["business_gstin"] == "29ABCDE1234F1Z5"
    assert s["invoice_prefix"] == "YH-" and s["invoice_padding"] == 5
    assert services.settings.is_setup_completed()
    assert [t["name"] for t in services.catalog.list_tax_rates()] == ["GST 5%"]
    kinds = {m["kind"] for m in services.payment_methods.list()}
    assert PaymentKind.OTHER not in kinds and PaymentKind.CASH in kinds
    services.auth.login("owner", GOOD_PW)
    wiz.close()


def test_setup_wizard_keeps_tax_rate_typed_but_not_added(qapp, services, dialogs):
    wiz = SetupWizard(services)
    _fill_wizard(wiz)
    wiz.tax.name.setText("GST 12%")
    wiz.tax.rate.setText("12")
    assert wiz.tax.validatePage()          # pressing Next adds it instead of dropping it
    assert wiz.tax.rates == [{"name": "GST 12%", "rate": "12.000"}]
    wiz.tax.name.setText("Half typed")      # name without a rate -> stays on the page
    assert not wiz.tax.validatePage()
    assert dialogs and "Tax rate" in dialogs[-1][1][2]
    wiz.close()


@pytest.mark.parametrize("page, setup, expected", [
    ("business", lambda w: w.business.name.setText(""), "Business name is required"),
    ("business", lambda w: w.business.gstin.setText("12345"), "GSTIN"),
    ("business", lambda w: w.business.email.setText("not-an-email"), "email"),
    ("admin", lambda w: w.admin.confirm.setText("different-123"), "do not match"),
    ("admin", lambda w: (w.admin.password.setText("short"), w.admin.confirm.setText("short")),
     "at least"),
    ("admin", lambda w: w.admin.username.setText("a b"), "Username"),
    ("billing", lambda w: w.billing.prefix.setText("INV#"), "prefix"),
    ("payments", lambda w: [c.setChecked(False) for c in w.payments.checks.values()],
     "at least one payment method"),
])
def test_setup_wizard_rejects_bad_input(qapp, services, dialogs, page, setup, expected):
    wiz = SetupWizard(services)
    _fill_wizard(wiz)
    setup(wiz)
    assert not getattr(wiz, page).validatePage()
    assert expected.lower() in dialogs[-1][1][2].lower()
    assert not services.settings.is_setup_completed()
    wiz.close()


# ---- sign-in -----------------------------------------------------------------------
def test_login_window_success_and_failure(qapp, services, admin, dialogs):
    win = LoginWindow(services)
    users = []
    win.logged_in.connect(users.append)
    win.username.setText("admin")
    win.password.setText("wrong-password")
    win._login()
    assert users == [] and "Invalid username or password" in win.error.text()
    win.password.setText(ADMIN_PASSWORD)
    win._login()
    assert len(users) == 1 and users[0].username == "admin"
    assert win.password.text() == ""        # password never left in the field
    win.close()


def test_login_window_shows_lockout(qapp, services, admin, dialogs):
    win = LoginWindow(services)
    win.username.setText("admin")
    for _ in range(5):
        win.password.setText("wrong-password")
        win._login()
    win.password.setText(ADMIN_PASSWORD)
    win._login()
    assert "locked" in win.error.text()
    win.close()


def test_login_forces_password_change(qapp, services, admin, dialogs, monkeypatch):
    from app.ui.dialogs import password_dialogs
    cashier = next(r["id"] for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "newcashier", "password": "Temp-Pass-1",
                                       "role_id": cashier, "must_change_password": True})
    win = LoginWindow(services)
    users = []
    win.logged_in.connect(users.append)

    # cancelling the forced change keeps the user out
    monkeypatch.setattr(password_dialogs.ChangePasswordDialog, "exec",
                        lambda self: QDialog.Rejected)
    win.username.setText("newcashier")
    win.password.setText("Temp-Pass-1")
    win._login()
    assert users == []

    def change(self):
        services.auth.change_password(services.auth.login("newcashier", "Temp-Pass-1"),
                                      "Temp-Pass-1", "Own-Pass-123")
        return QDialog.Accepted
    monkeypatch.setattr(password_dialogs.ChangePasswordDialog, "exec", change)
    win.password.setText("Temp-Pass-1")
    win._login()
    assert len(users) == 1
    services.auth.login("newcashier", "Own-Pass-123")
    win.close()
