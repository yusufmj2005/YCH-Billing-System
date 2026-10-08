"""UPI QR payments at checkout."""
from __future__ import annotations

import os
from decimal import Decimal as D
from urllib.parse import parse_qs, urlsplit

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.payments.upi import qr_matrix, upi_uri, validate_upi_id  # noqa: E402
from app.services.errors import ValidationError  # noqa: E402


@pytest.mark.parametrize("good", ["yarnshop@okaxis", "9876543210@ybl", "shop.name-1@paytm",
                                  "a_b@oksbi", "  padded@upi  "])
def test_valid_upi_ids(good):
    assert validate_upi_id(good) == good.strip()


@pytest.mark.parametrize("bad", ["yarnshop", "@okaxis", "shop@", "shop@@ok", "sh op@ok",
                                 "shop@ok axis", "shop@1bank", "x@y"])
def test_invalid_upi_ids(bad):
    with pytest.raises(ValidationError):
        validate_upi_id(bad)


def test_blank_upi_id_means_off():
    assert validate_upi_id("") == "" and validate_upi_id(None) == ""


def test_upi_uri_contains_exact_amount_and_encoded_names():
    uri = upi_uri("yarnshop@okaxis", "Yarn & Hook Store", "589", "Bill #12")
    parts = urlsplit(uri)
    assert parts.scheme == "upi" and parts.netloc == "pay"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q == {"pa": "yarnshop@okaxis", "pn": "Yarn & Hook Store", "am": "589.00",
                 "cu": "INR", "tn": "Bill #12"}
    assert "&tn=Bill%20%2312" in uri          # special characters never break the link
    assert upi_uri("a1@ybl", "", D("10.005")).count("am=10.01") == 1   # rounded to paise
    assert "pn=a1%40ybl" in upi_uri("a1@ybl", "", 5)                     # name falls back to ID


@pytest.mark.parametrize("upi_id, amount, msg", [("", 10, "Settings"), ("a1@ybl", 0, "greater"),
                                                 ("a1@ybl", -5, "greater"), ("bad", 10, "UPI ID")])
def test_upi_uri_rejects_bad_input(upi_id, amount, msg):
    with pytest.raises(ValidationError, match=msg):
        upi_uri(upi_id, "Shop", amount)


def test_qr_matrix_has_finder_patterns():
    m = qr_matrix(upi_uri("yarnshop@okaxis", "Shop", 100))
    n = len(m)
    assert n >= 21 and (n - 21) % 4 == 0 and all(len(r) == n for r in m)
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):          # the three corner squares
        assert all(m[r0][c0 + i] and m[r0 + 6][c0 + i] for i in range(7))
        assert all(m[r0 + i][c0] and m[r0 + i][c0 + 6] for i in range(7))
        assert not m[r0 + 1][c0 + 1] and m[r0 + 3][c0 + 3]


def test_upi_settings_validated_and_saved(services, admin):
    with pytest.raises(ValidationError):
        services.settings.update(admin, {"upi_id": "not-a-upi-id"})
    services.settings.update(admin, {"upi_id": " yarnshop@okaxis ", "upi_payee_name": "Yarn Shop"})
    s = services.settings.get_all()
    assert s["upi_id"] == "yarnshop@okaxis" and s["upi_payee_name"] == "Yarn Shop"


# ---- UI --------------------------------------------------------------------------
@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def test_qr_pixmap_matches_matrix(qapp):
    from app.ui.dialogs.upi_dialog import qr_pixmap
    uri = upi_uri("yarnshop@okaxis", "Shop", 250)
    m = qr_matrix(uri)
    size = 400
    img = qr_pixmap(uri, size).toImage()
    cell = size / (len(m) + 8)
    for r, row in enumerate(m):
        for c, dark in enumerate(row):
            px = img.pixelColor(int((c + 4.5) * cell), int((r + 4.5) * cell))
            assert (px.lightness() < 128) == dark, (r, c)


def _checkout_factory(services, admin, make_product, monkeypatch):
    from app.services.sales_service import SaleLineRequest, SaleRequest
    from app.ui.context import AppContext
    from app.ui.dialogs import checkout_dialog as cd
    from app.ui.windows.main_window import MainWindow
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(cd.SaleCompleteDialog, "exec", lambda self: 0)
    pid = make_product(stock="5", price="250")

    def checkout(user=admin):
        win = MainWindow(AppContext(services=services, user=user))
        win.navigate("pos")
        pos = win.pages["pos"]
        pos.add_product(services.catalog.get_product(admin, pid))
        req = SaleRequest(lines=[SaleLineRequest(pid, D(1))])
        dlg = cd.CheckoutDialog(win, win.ctx, pos.compute(), req)
        upi = next(i for i, m in enumerate(dlg.methods) if m["kind"] == "UPI")
        return win, dlg, dlg.method_group.button(upi)
    return checkout, shown


def _fake_qr(monkeypatch, answer=1):
    from app.ui.dialogs import upi_dialog
    seen = []

    def fake_exec(self):
        seen.append(self.uri)
        return answer                    # 1 = cashier clicks "Payment received"
    monkeypatch.setattr(upi_dialog.UpiQrDialog, "exec", fake_exec)
    return seen


def test_selecting_upi_opens_the_qr_for_the_amount_due(qapp, services, admin, make_product,
                                                       monkeypatch):
    checkout, shown = _checkout_factory(services, admin, make_product, monkeypatch)
    services.settings.update(admin, {"upi_id": "yarnshop@okaxis", "upi_payee_name": "Yarn Shop"})
    seen = _fake_qr(monkeypatch)
    win, dlg, upi_btn = checkout()
    assert seen == []                               # Cash is the default; no QR yet
    dlg.amount.setText("100")                       # cash part first
    assert dlg._add_payment()
    upi_btn.click()                                 # choosing UPI opens the QR at once
    assert len(seen) == 1 and "am=150.00" in seen[0] and "pa=yarnshop@okaxis" in seen[0]
    assert [(p["method"]["kind"], p["amount"]) for p in dlg.payments] == [
        ("CASH", D("100")), ("UPI", D("150.00"))]
    assert not dlg.upi_btn.isHidden()               # can be shown again from the button
    upi_btn.click()                                 # nothing left to pay: no second QR
    assert len(seen) == 1
    dlg._complete()
    assert dlg.sale is not None, shown
    sale = services.sales.get_sale(admin, dlg.sale["sale_id"])
    assert [(p["method"], p["amount"]) for p in sale["payments"]] == [
        ("Cash", D("100.00")), ("UPI", D("150.00"))]
    win.close()


def test_closing_the_qr_records_nothing(qapp, services, admin, make_product, monkeypatch):
    checkout, _ = _checkout_factory(services, admin, make_product, monkeypatch)
    services.settings.update(admin, {"upi_id": "yarnshop@okaxis"})
    seen = _fake_qr(monkeypatch, answer=0)          # cashier clicks Cancel
    win, dlg, upi_btn = checkout()
    upi_btn.click()
    assert len(seen) == 1 and "am=250.00" in seen[0]
    assert dlg.payments == [] and dlg.amount.text() == "250.00"
    win.close()


def test_first_upi_click_asks_admin_for_the_upi_id(qapp, services, admin, make_product,
                                                   monkeypatch):
    from app.ui.dialogs import checkout_dialog as cd
    checkout, _ = _checkout_factory(services, admin, make_product, monkeypatch)
    seen = _fake_qr(monkeypatch)
    asked = []

    def fill(self):                                  # admin types the ID and saves
        asked.append(self.windowTitle())
        self.widgets["upi_id"].setText(" 9840566252@slc ")
        self._submit()
        return self.result()
    monkeypatch.setattr(cd.FormDialog, "exec", fill)
    win, dlg, upi_btn = checkout()
    upi_btn.click()
    assert asked == ["Set up UPI QR"]
    assert services.settings.get_all()["upi_id"] == "9840566252@slc"
    assert len(seen) == 1 and "pa=9840566252@slc" in seen[0] and "am=250.00" in seen[0]
    assert [p["method"]["kind"] for p in dlg.payments] == ["UPI"]
    assert not dlg.upi_btn.isHidden()
    win.close()

    # "Not now" shows no QR, records nothing, and is not asked again this session
    services.settings.update(admin, {"upi_id": ""})
    seen.clear()
    asked.clear()

    def decline(self):
        asked.append(self.findChild(cd.QDialogButtonBox).button(
            cd.QDialogButtonBox.Cancel).text())
        return 0
    monkeypatch.setattr(cd.FormDialog, "exec", decline)
    win, dlg, upi_btn = checkout()
    upi_btn.click()
    assert asked == ["Not now"]
    assert seen == [] and dlg.payments == [] and dlg.upi_btn.isHidden()
    assert not dlg.upi_hint.isHidden() and "Settings › Payments" in dlg.upi_hint.text()
    upi_btn.click()
    assert asked == ["Not now"] and seen == []
    win.close()


def test_cashier_without_upi_id_sees_a_note_not_a_prompt(qapp, services, admin, make_product,
                                                         monkeypatch):
    from app.ui.dialogs import checkout_dialog as cd
    checkout, _ = _checkout_factory(services, admin, make_product, monkeypatch)
    seen = _fake_qr(monkeypatch)
    monkeypatch.setattr(cd.FormDialog, "exec",
                        lambda self: pytest.fail("cashier must not get the set-up form"))
    role = next(r["id"] for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "cashier", "password": "Cashier-123",
                                       "role_id": role, "must_change_password": False})
    win, dlg, upi_btn = checkout(services.auth.login("cashier", "Cashier-123"))
    upi_btn.click()
    assert seen == [] and dlg.upi_btn.isHidden() and not dlg.upi_hint.isHidden()
    dlg._complete()                                 # UPI can still be recorded by hand
    assert dlg.sale is not None
    win.close()
