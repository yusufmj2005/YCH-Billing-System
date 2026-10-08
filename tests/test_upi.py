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


def test_checkout_upi_qr_flow(qapp, services, admin, make_product, monkeypatch):
    from app.ui.context import AppContext
    from app.ui.dialogs import checkout_dialog as cd
    from app.ui.dialogs import upi_dialog
    from app.ui.windows.main_window import MainWindow
    from app.services.sales_service import SaleLineRequest, SaleRequest
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(cd.SaleCompleteDialog, "exec", lambda self: 0)
    pid = make_product(stock="5", price="250")
    req = SaleRequest(lines=[SaleLineRequest(pid, D(1))])

    def checkout():
        win = MainWindow(AppContext(services=services, user=admin))
        win.navigate("pos")
        pos = win.pages["pos"]
        pos.add_product(services.catalog.get_product(admin, pid))
        return win, cd.CheckoutDialog(win, win.ctx, pos.compute(), req)

    # no UPI ID configured: the QR button stays hidden
    win, dlg = checkout()
    upi = next(i for i, m in enumerate(dlg.methods) if m["kind"] == "UPI")
    dlg.method_group.button(upi).click()
    assert dlg.upi_btn.isHidden()
    win.close()

    services.settings.update(admin, {"upi_id": "yarnshop@okaxis", "upi_payee_name": "Yarn Shop"})
    win, dlg = checkout()
    dlg.amount.setText("100")                       # cash part first
    assert dlg._add_payment()
    dlg.method_group.button(upi).click()
    assert not dlg.upi_btn.isHidden() and dlg.amount.text() == "150.00"
    seen = {}

    def fake_exec(self):
        seen["uri"] = self.uri
        return 1                                    # cashier clicks "Payment received"
    monkeypatch.setattr(upi_dialog.UpiQrDialog, "exec", fake_exec)
    dlg._show_upi_qr()
    assert "am=150.00" in seen["uri"] and "pa=yarnshop@okaxis" in seen["uri"]
    assert [(p["method"]["kind"], p["amount"]) for p in dlg.payments] == [
        ("CASH", D("100")), ("UPI", D("150.00"))]
    dlg._complete()
    assert dlg.sale is not None, shown
    sale = services.sales.get_sale(admin, dlg.sale["sale_id"])
    assert [(p["method"], p["amount"]) for p in sale["payments"]] == [
        ("Cash", D("100.00")), ("UPI", D("150.00"))]
    win.close()
