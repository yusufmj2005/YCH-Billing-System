"""Razorpay: client, service rules and the real checkout / settings screens, against a
simulated Razorpay API (same routes, auth and error format as api.razorpay.com)."""
from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
from datetime import date, datetime
from decimal import Decimal as D
from urllib.parse import parse_qs, urlparse

import pytest
from PySide6.QtWidgets import QMessageBox

from app.config.constants import PaymentKind
from app.payments import razorpay as rp
from app.services.errors import PermissionDenied, ValidationError
from app.services.razorpay_service import NotConnected
from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest

KEY, SECRET = "rzp_test_ABCdef123456", "S3cretKeyValue1234"


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeRazorpay:
    """In-memory stand-in for api.razorpay.com (and rzp.io for the QR image)."""

    def __init__(self, key=KEY, secret=SECRET):
        self.auth = "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
        self.qrs, self.links, self.payments = {}, {}, {}
        self.calls: list[tuple] = []
        self.offline = False
        self.qr_enabled = True
        self.reject_close_by = False
        self.n = 0
        self.png = _png()

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}_T{self.n:012d}"

    def _err(self, status, desc, code="BAD_REQUEST_ERROR"):
        return status, json.dumps({"error": {"code": code, "description": desc}}).encode()

    def _ok(self, data):
        return 200, json.dumps(data).encode()

    def make_payment(self, amount_paise, method="upi", status="captured", **extra):
        pid = self._id("pay")
        p = {"id": pid, "entity": "payment", "amount": amount_paise, "currency": "INR",
             "status": status, "method": method, "amount_refunded": 0, "captured": True,
             "vpa": "customer@okaxis" if method == "upi" else None,
             "created_at": int(time.time()), **extra}
        self.payments[pid] = p
        return p

    def pay_qr(self, qr_id, amount_paise=None, method="upi"):
        qr = self.qrs[qr_id]
        assert qr["status"] == "active", "customer cannot pay a closed QR"
        p = self.make_payment(amount_paise or qr["payment_amount"], method)
        qr["_payments"].append(p["id"])
        qr["payments_amount_received"] += p["amount"]
        qr["payments_count_received"] += 1
        if qr["usage"] == "single_use":
            qr["status"], qr["close_reason"] = "closed", "paid"
        return p

    def pay_link(self, link_id, method="card"):
        link = self.links[link_id]
        assert link["status"] == "created", "customer cannot pay a cancelled link"
        p = self.make_payment(link["amount"], method)
        link["payments"].append({"amount": p["amount"], "created_at": p["created_at"],
                                 "method": method, "payment_id": p["id"],
                                 "status": "captured"})
        link["status"], link["amount_paid"] = "paid", p["amount"]
        return p

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        if self.offline:
            raise urllib.error.URLError("network is unreachable")
        if url.startswith("https://rzp.io/"):
            assert "Authorization" not in headers, "credentials must not go to rzp.io"
            return 200, self.png
        assert url.startswith(rp.API + "/"), url
        if headers.get("Authorization") != self.auth:
            return self._err(401, "Authentication failed", "BAD_REQUEST_ERROR")
        u = urlparse(url)
        path = u.path[len("/v1"):]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        data = json.loads(body) if body else {}
        parts = path.strip("/").split("/")
        if parts == ["payments"] and method == "GET":
            items = [p for p in self.payments.values()
                     if int(q.get("from", 0)) <= p["created_at"] <= int(q.get("to", 2**40))]
            skip, count = int(q.get("skip", 0)), int(q.get("count", 10))
            return self._ok({"entity": "collection", "count": len(items),
                             "items": items[skip:skip + count]})
        if parts[0] == "payments" and len(parts) == 2 and parts[1].startswith("pay_"):
            p = self.payments.get(parts[1])
            return self._ok(p) if p else self._err(400, "The id provided does not exist")
        if parts[:2] == ["payments", "qr_codes"]:
            if len(parts) == 2 and method == "POST":
                if not self.qr_enabled:
                    return self._err(400, "QR code feature is not enabled for this merchant")
                assert data["type"] == "upi_qr" and data["usage"] == "single_use"
                assert data["fixed_amount"] is True and isinstance(data["payment_amount"], int)
                if "close_by" in data:
                    if self.reject_close_by:
                        return self._err(400, "close_by should be at least 2 minutes after "
                                              "current time")
                    assert data["close_by"] > time.time() + 120
                qid = self._id("qr")
                qr = {"id": qid, "entity": "qr_code", "status": "active",
                      "image_url": f"https://rzp.io/i/{qid[-6:]}", "close_reason": None,
                      "payments_amount_received": 0, "payments_count_received": 0,
                      "_payments": [], **data}
                self.qrs[qid] = qr
                return self._ok({k: v for k, v in qr.items() if not k.startswith("_")})
            qr = self.qrs.get(parts[2])
            if qr is None:
                return self._err(400, "The id provided does not exist")
            if parts[3:] == ["payments"]:
                return self._ok({"entity": "collection", "count": len(qr["_payments"]),
                                 "items": [self.payments[i] for i in qr["_payments"]]})
            if parts[3:] == ["close"]:
                if qr["status"] == "closed":
                    return self._err(400, "QR code is already closed")
                qr["status"], qr["close_reason"] = "closed", "on_demand"
                return self._ok({k: v for k, v in qr.items() if not k.startswith("_")})
        if parts[0] == "payment_links":
            if len(parts) == 1 and method == "POST":
                assert data["currency"] == "INR" and data["accept_partial"] is False
                assert isinstance(data["amount"], int)
                if "expire_by" in data:
                    assert data["expire_by"] > time.time() + 15 * 60
                lid = self._id("plink")
                link = {"id": lid, "status": "created", "amount_paid": 0, "payments": [],
                        "short_url": f"https://rzp.io/l/{lid[-6:]}", **data}
                self.links[lid] = link
                return self._ok(link)
            link = self.links.get(parts[1])
            if link is None:
                return self._err(400, "The id provided does not exist")
            if len(parts) == 2:
                return self._ok(link)
            if parts[2] == "cancel":
                if link["status"] == "paid":
                    return self._err(400, "Payment link cannot be cancelled as it is "
                                          "already paid")
                link["status"] = "cancelled"
                return self._ok(link)
        return self._err(404, "The requested URL was not found on the server.")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    from app.ui.styles.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture()
def fake(services):
    f = FakeRazorpay()
    services.razorpay.transport = f
    return f


@pytest.fixture()
def connected(services, admin, fake):
    services.razorpay.connect(admin, KEY, SECRET)
    return fake


def _cashier(services, admin):
    role = next(r["id"] for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "cashier", "password": "Cashier-123",
                                       "role_id": role, "must_change_password": False})
    return services.auth.login("cashier", "Cashier-123")


# ---- client ---------------------------------------------------------------------------
@pytest.mark.parametrize("key,secret", [("rzp_live_ABCdef123456", "abcDEF1234567890"),
                                         (" rzp_test_ABCdef123456 ", " S3cretKeyValue1234 ")])
def test_valid_keys(key, secret):
    assert rp.validate_keys(key, secret) == (key.strip(), secret.strip())


@pytest.mark.parametrize("key,secret", [("", SECRET), ("rzp_ABC123456", SECRET),
                                         ("rzp_prod_ABCdef123456", SECRET), (KEY, ""),
                                         (KEY, "short"), (KEY, "has space in it 123")])
def test_invalid_keys(key, secret):
    with pytest.raises(ValidationError):
        rp.validate_keys(key, secret)


def test_amounts_go_to_razorpay_in_paise():
    assert rp.paise("150") == 15000 and rp.paise(D("0.01")) == 1 and rp.paise("10.005") == 1001
    assert rp.rupees(15000) == D("150.00") and rp.rupees(1) == D("0.01")


def test_client_auth_and_errors():
    f = FakeRazorpay()
    rp.RazorpayClient(KEY, SECRET, transport=f).verify()
    method, url, headers, _ = f.calls[-1]
    assert method == "GET" and url.startswith("https://api.razorpay.com/v1/payments?")
    assert headers["Authorization"] == f.auth and headers["User-Agent"].startswith("BusinessPOS/")
    with pytest.raises(rp.RazorpayError, match="did not accept") as e:
        rp.RazorpayClient(KEY, "WrongSecret12345", transport=f).verify()
    assert e.value.status == 401 and not e.value.network
    f.offline = True
    with pytest.raises(rp.RazorpayError, match="internet") as e:
        rp.RazorpayClient(KEY, SECRET, transport=f).verify()
    assert e.value.network
    with pytest.raises(rp.RazorpayError, match="having a problem") as e:
        rp.RazorpayClient(KEY, SECRET, transport=lambda *a: (502, b"<html>")).verify()
    assert e.value.network


def test_ids_from_razorpay_are_checked_before_use_in_urls():
    c = rp.RazorpayClient(KEY, SECRET, transport=FakeRazorpay())
    for bad in ("../payments", "qr_1/close", "", "pay_x?count=100"):
        with pytest.raises(rp.RazorpayError):
            c.qr_payments(bad)
    with pytest.raises(rp.RazorpayError):
        c.fetch_image("http://rzp.io/i/abc")          # https only


# ---- collections --------------------------------------------------------------------
def test_qr_collection_detects_only_the_exact_captured_payment():
    f = FakeRazorpay()
    c = rp.QrCollection(rp.RazorpayClient(KEY, SECRET, transport=f), "150", shop="Yarn Shop",
                        note="Bill")
    data = c.start()
    qr = f.qrs[c.id]
    assert qr["payment_amount"] == 15000 and qr["name"] == "Yarn Shop"
    assert qr["notes"]["source"] == "BusinessPOS" and data["image_url"].startswith("https://")
    assert c.check() is None
    f.payments["pay_T999999999999"] = {"id": "pay_T999999999999", "amount": 15000,
                                       "status": "authorized", "method": "upi",
                                       "created_at": int(time.time())}
    qr["_payments"].append("pay_T999999999999")          # not captured yet: keep waiting
    assert c.check() is None
    p = f.pay_qr(c.id)
    res = c.check()
    assert res == rp.PaidResult(p["id"], D("150.00"), "upi", "customer@okaxis")
    assert res.description == "UPI via Razorpay"


def test_qr_wrong_amount_is_not_accepted():
    f = FakeRazorpay()
    c = rp.QrCollection(rp.RazorpayClient(KEY, SECRET, transport=f), "150", shop="S", note="n")
    c.start()
    f.pay_qr(c.id, amount_paise=100)
    assert c.check() is None


def test_qr_retries_without_auto_close_when_pc_clock_is_wrong():
    f = FakeRazorpay()
    f.reject_close_by = True
    c = rp.QrCollection(rp.RazorpayClient(KEY, SECRET, transport=f), "5", shop="S", note="n")
    c.start()
    assert "close_by" not in f.qrs[c.id]


def test_cancel_closes_the_qr_but_never_loses_a_last_moment_payment():
    f = FakeRazorpay()
    client = rp.RazorpayClient(KEY, SECRET, transport=f)
    c = rp.QrCollection(client, "20", shop="S", note="n")
    c.start()
    assert c.cancel() is None and f.qrs[c.id]["status"] == "closed"
    c2 = rp.QrCollection(client, "20", shop="S", note="n")
    c2.start()
    p = f.pay_qr(c2.id)                  # paid just before the cashier pressed Cancel
    assert c2.cancel().payment_id == p["id"]
    f.offline = True
    c3 = rp.QrCollection(rp.RazorpayClient(KEY, SECRET, transport=f), "1", shop="S", note="n")
    c3.id = "qr_T000000000123"
    with pytest.raises(rp.RazorpayError):
        c3.cancel()                       # unknown outcome is reported, not hidden


def test_payment_link_collection():
    f = FakeRazorpay()
    client = rp.RazorpayClient(KEY, SECRET, transport=f)
    c = rp.LinkCollection(client, "499.50", shop="Yarn Shop", note="Bill",
                          contact="98405 66252", customer="Anu")
    data = c.start()
    link = f.links[c.id]
    assert link["amount"] == 49950 and link["customer"] == {"name": "Anu",
                                                            "contact": "+919840566252"}
    assert link["notify"] == {"sms": True, "email": False} and data["short_url"]
    assert c.check() is None
    p = f.pay_link(c.id, method="card")
    res = c.check()
    assert res.payment_id == p["id"] and res.amount == D("499.50")
    assert res.description == "Card via Razorpay"
    assert c.cancel().payment_id == p["id"]          # cannot cancel a paid link: still found
    c2 = rp.LinkCollection(client, "10", shop="S", note="n")
    c2.start()
    assert f.links[c2.id]["notify"]["sms"] is False and "customer" not in f.links[c2.id]
    assert c2.cancel() is None and f.links[c2.id]["status"] == "cancelled"
    with pytest.raises(ValidationError, match="mobile"):
        rp.LinkCollection(client, "10", shop="S", note="n", contact="12345")
    with pytest.raises(ValidationError):
        rp.QrCollection(client, "0", shop="S", note="n")


# ---- service ----------------------------------------------------------------------------
def test_connect_stores_protected_secret_and_enables_method(services, admin, fake):
    assert services.razorpay.status()["connected"] is False
    assert services.razorpay.method() is None
    with pytest.raises(NotConnected):
        services.razorpay.client()
    with pytest.raises(rp.RazorpayError, match="did not accept"):
        services.razorpay.connect(admin, KEY, "WrongSecret12345")
    assert services.razorpay.status()["key_id"] == ""          # nothing saved on failure
    st = services.razorpay.connect(admin, KEY, SECRET)
    assert st == {"connected": True, "key_id": KEY, "needs_secret": False, "mode": "test"}
    m = services.razorpay.method()
    assert m["kind"] == PaymentKind.RAZORPAY and m["is_active"] and m["name"] == "Razorpay"
    assert m["id"] in [x["id"] for x in services.payment_methods.list()]
    # the secret is never exposed through settings, and never written in clear text
    assert SECRET not in json.dumps(services.settings.get_all(), default=str)
    from app.models import AuditLog, Setting
    with services.db.session() as s:
        stored = s.get(Setting, "secret_razorpay_key_secret").value
        audit = " ".join(a.details or "" for a in s.query(AuditLog))
    assert SECRET not in stored and SECRET not in audit and "RAZORPAY" not in stored
    assert services.razorpay.client().key_id == KEY


def test_connect_adopts_a_hand_made_razorpay_method(services, admin, fake):
    mid = services.payment_methods.save(admin, None, {"name": "Razorpay", "is_active": False,
                                                      "allows_reference": False})
    services.razorpay.connect(admin, KEY, SECRET)
    m = services.razorpay.method()
    assert m["id"] == mid and m["kind"] == PaymentKind.RAZORPAY
    assert m["is_active"] and m["allows_reference"]
    services.payment_methods.save(admin, mid, {"name": "Razorpay", "allows_reference": False})
    assert services.razorpay.method()["allows_reference"] is True   # holds the pay_ ID


def test_disconnect_and_unreadable_secret(services, admin, connected):
    from app.models import Setting
    with services.db.session() as s:
        s.get(Setting, "secret_razorpay_key_secret").value = json.dumps("dpapi:AAAA")
    st = services.razorpay.status()
    assert st["connected"] is False and st["needs_secret"] is True
    with pytest.raises(NotConnected, match="again"):
        services.razorpay.client()
    services.razorpay.disconnect(admin)
    assert services.razorpay.status() == {"connected": False, "key_id": "", "needs_secret": False,
                                          "mode": ""}
    assert services.razorpay.method()["is_active"] is False


def test_only_settings_managers_can_connect(services, admin, fake):
    cashier = _cashier(services, admin)
    with pytest.raises(PermissionDenied):
        services.razorpay.connect(cashier, KEY, SECRET)
    services.razorpay.connect(admin, KEY, SECRET)
    with pytest.raises(PermissionDenied):
        services.razorpay.disconnect(cashier)
    with pytest.raises(PermissionDenied):
        services.razorpay.reconcile(cashier, date.today())


def _sale(services, admin, pid, refs, amounts=("250",)):
    rzp = services.razorpay.method()["id"]
    return services.sales.create_sale(admin, SaleRequest(
        lines=[SaleLineRequest(pid, D(1))],
        payments=[PaymentRequest(rzp, D(a), r) for a, r in zip(amounts, refs)]))


def test_sales_need_a_unique_razorpay_payment_id(services, admin, connected, make_product):
    pid = make_product(stock="10", price="250")
    for bad in (None, "12345", "rfnd_ABC123456"):
        with pytest.raises(ValidationError, match="Razorpay button"):
            _sale(services, admin, pid, [bad])
    with pytest.raises(ValidationError, match="already recorded"):
        _sale(services, admin, pid, ["pay_AAA111222333", "pay_AAA111222333"], ("100", "150"))
    sale = _sale(services, admin, pid, ["pay_AAA111222333"])
    with pytest.raises(ValidationError, match=sale["invoice_no"]):
        _sale(services, admin, pid, ["pay_AAA111222333"])
    assert services.razorpay.used_on("pay_AAA111222333") == sale["invoice_no"]


def test_existing_payment_checks(services, admin, connected, make_product):
    f = connected
    ok = f.make_payment(25000)
    res = services.razorpay.existing_payment(admin, f" {ok['id']} ", D("250"))
    assert res.payment_id == ok["id"] and res.amount == D("250.00")
    with pytest.raises(ValidationError, match="is for ₹250.00, not ₹251.00"):
        services.razorpay.existing_payment(admin, ok["id"], D("250.00") + 1)
    with pytest.raises(ValidationError, match="not captured"):
        services.razorpay.existing_payment(admin, f.make_payment(25000, status="failed")["id"],
                                           D("250"))
    with pytest.raises(ValidationError, match="refunded"):
        services.razorpay.existing_payment(
            admin, f.make_payment(25000, amount_refunded=25000)["id"], D("250"))
    with pytest.raises(ValidationError, match="no payment"):
        services.razorpay.existing_payment(admin, "pay_NOSUCH123456", D("250"))
    with pytest.raises(ValidationError, match="payment ID"):
        services.razorpay.existing_payment(admin, "plink_123", D("250"))
    sale = _sale(services, admin, make_product(stock="2", price="250"), [ok["id"]])
    with pytest.raises(ValidationError, match=sale["invoice_no"]):
        services.razorpay.existing_payment(admin, ok["id"], D("250"))


def test_reconcile_shows_unrecorded_and_unknown_payments(services, admin, connected,
                                                         make_product):
    f = connected
    pid = make_product(stock="10", price="250")
    recorded = f.make_payment(25000)
    sale = _sale(services, admin, pid, [recorded["id"]])
    lost = f.make_payment(9900)                           # paid, but no sale was saved
    f.make_payment(5000, status="failed")
    _sale(services, admin, pid, ["pay_LOCALONLY1234"])    # recorded, unknown at Razorpay
    res = services.razorpay.reconcile(admin, date.today())
    by_id = {r["payment_id"]: r for r in res["rows"]}
    assert by_id[recorded["id"]]["invoice"] == f"Invoice {sale['invoice_no']}"
    assert by_id[lost["id"]]["invoice"] == "NOT RECORDED in BusinessPOS"
    assert by_id["pay_LOCALONLY1234"]["status"] == "Not found at Razorpay"
    assert res["not_recorded"] == 1 and res["unknown"] == 1
    assert res["captured_total"] == D("349.00") and res["recorded_total"] == D("500.00")
    assert services.razorpay.reconcile(admin, date(2001, 1, 1))["rows"] == []


# ---- screens ------------------------------------------------------------------------------
@pytest.fixture()
def ui(qapp, services, admin, make_product, monkeypatch):
    from app.services.sales_service import SaleLineRequest, SaleRequest
    from app.ui.context import AppContext
    from app.ui.dialogs import checkout_dialog as cd
    from app.ui.dialogs import razorpay_dialog
    from app.ui.windows.main_window import MainWindow
    monkeypatch.setattr(razorpay_dialog, "RUN_ASYNC", False)
    msgs = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _n=name, **k: msgs.append((_n, a)))
    monkeypatch.setattr(cd.SaleCompleteDialog, "exec", lambda self: 0)
    pid = make_product(stock="5", price="250")
    wins = []

    def checkout(user=admin):
        win = MainWindow(AppContext(services=services, user=user))
        wins.append(win)
        win.navigate("pos")
        pos = win.pages["pos"]
        pos.add_product(services.catalog.get_product(admin, pid))
        req = SaleRequest(lines=[SaleLineRequest(pid, D(1))])
        dlg = cd.CheckoutDialog(win, win.ctx, pos.compute(), req)
        idx = {m["kind"]: i for i, m in enumerate(dlg.methods)}
        return dlg, idx
    yield checkout, msgs
    for w in wins:
        w.close()


def _drive(monkeypatch, steps):
    """Replace RazorpayDialog.exec: run the start step, then ``steps(dialog)``."""
    from PySide6.QtWidgets import QApplication

    from app.ui.dialogs import razorpay_dialog
    seen = []

    def fake_exec(self):
        seen.append(self)
        QApplication.processEvents()          # the dialog starts the UPI QR on open
        steps(self)
        return self.result()
    monkeypatch.setattr(razorpay_dialog.RazorpayDialog, "exec", fake_exec)
    return seen


def test_checkout_has_no_razorpay_button_until_connected(ui, services, admin, fake):
    checkout, _ = ui
    dlg, idx = checkout()
    assert PaymentKind.RAZORPAY not in idx
    services.razorpay.connect(admin, KEY, SECRET)
    dlg, idx = checkout()
    assert PaymentKind.RAZORPAY in idx


def test_checkout_collects_with_razorpay_qr_and_completes(ui, services, admin, connected,
                                                          monkeypatch):
    checkout, msgs = ui
    f = connected

    def customer_pays(d):
        assert d.collection.kind == "qr" and not d.qr.pixmap().isNull()
        assert "Waiting" in d.status.text() and d.client.test_mode
        d._poll()
        assert d.paid is None                       # nothing paid yet
        f.pay_qr(d.collection.id)
        d._poll()
    seen = _drive(monkeypatch, customer_pays)
    dlg, idx = checkout()
    dlg.amount.setText("100")
    assert dlg._add_payment()                       # cash part
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert len(seen) == 1 and seen[0].amount == D("150.00")
    qr = next(iter(f.qrs.values()))
    assert qr["payment_amount"] == 15000
    assert dlg.reference.isHidden() and not dlg.rzp_btn.isHidden()
    rzp = dlg.payments[-1]
    assert rzp["reference"].startswith("pay_") and rzp["description"] == "UPI via Razorpay"
    dlg._complete()
    assert dlg.sale is not None, msgs
    sale = services.sales.get_sale(admin, dlg.sale["sale_id"])
    assert [(p["method"], p["amount"]) for p in sale["payments"]] == [
        ("Cash", D("100.00")), ("Razorpay", D("150.00"))]
    assert sale["payments"][1]["reference"] == rzp["reference"]


def test_cancel_closes_qr_and_records_nothing(ui, connected, monkeypatch):
    checkout, _ = ui
    f = connected
    _drive(monkeypatch, lambda d: d.reject())
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert dlg.payments == []
    assert [q["status"] for q in f.qrs.values()] == ["closed"]


def test_payment_made_while_cashier_cancels_is_still_recorded(ui, connected, monkeypatch):
    checkout, msgs = ui
    f = connected

    def pay_then_cancel(d):
        f.pay_qr(d.collection.id)
        d.reject()
    _drive(monkeypatch, pay_then_cancel)
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert len(dlg.payments) == 1 and dlg.payments[0]["amount"] == D("250.00")
    assert any("just paid" in str(m) for m in msgs)


def test_payment_link_mode(ui, connected, monkeypatch):
    checkout, _ = ui
    f = connected

    def use_link(d):
        d.mode_group.button(1).click()                # switching closes the QR first
        assert [q["status"] for q in f.qrs.values()] == ["closed"]
        assert not d.phone.isHidden()
        d.phone.setText("9840566252")
        d.link_btn.click()
        link = next(iter(f.links.values()))
        assert link["customer"]["contact"] == "+919840566252"
        assert d.link_lbl.text() == link["short_url"]
        f.pay_link(link["id"], method="netbanking")
        d._poll()
    _drive(monkeypatch, use_link)
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert dlg.payments[0]["description"] == "Net banking via Razorpay"
    dlg._complete()
    assert dlg.sale is not None


def test_qr_not_enabled_suggests_payment_link(ui, connected, monkeypatch):
    checkout, msgs = ui
    connected.qr_enabled = False
    _drive(monkeypatch, lambda d: d.reject())
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert any("Payment link instead" in str(m) for m in msgs) and dlg.payments == []


def test_network_drop_while_waiting_keeps_checking(ui, connected, monkeypatch):
    checkout, _ = ui
    f = connected

    def flaky(d):
        f.offline = True
        d._poll()
        assert "Connection problem" in d.status.text() and d.timer.isActive()
        f.offline = False
        f.pay_qr(d.collection.id)
        d._poll()
    _drive(monkeypatch, flaky)
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert len(dlg.payments) == 1


def test_already_paid_payment_id(ui, connected, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    checkout, _ = ui
    f = connected
    earlier = f.make_payment(25000)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (earlier["id"], True))
    _drive(monkeypatch, lambda d: d._existing())
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    assert dlg.payments[0]["reference"] == earlier["id"]
    assert [q["status"] for q in f.qrs.values()] == ["closed"]   # the new QR was withdrawn


def test_leaving_checkout_after_razorpay_payment_asks_first(ui, connected, monkeypatch):
    from app.ui.dialogs import checkout_dialog as cd
    checkout, _ = ui
    f = connected
    _drive(monkeypatch, lambda d: (f.pay_qr(d.collection.id), d._poll()))
    dlg, idx = checkout()
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    asked = []
    monkeypatch.setattr(cd, "confirm", lambda *a, **k: asked.append(a[1]) or False)
    dlg.reject()
    assert dlg.result() == 0 and "Razorpay Dashboard" in asked[0] and dlg.payments
    dlg._remove_payment(0)
    assert len(asked) == 2 and dlg.payments           # removal also asks, and was refused


def test_cashier_sees_razorpay_but_cannot_connect(ui, services, admin, connected, monkeypatch):
    checkout, _ = ui
    f = connected
    _drive(monkeypatch, lambda d: (f.pay_qr(d.collection.id), d._poll()))
    dlg, idx = checkout(_cashier(services, admin))
    dlg.method_group.button(idx[PaymentKind.RAZORPAY]).click()
    dlg._complete()
    assert dlg.sale is not None


def test_settings_connect_and_check_screens(qapp, services, admin, fake, monkeypatch):
    from app.ui.context import AppContext
    from app.ui.dialogs.razorpay_check_dialog import RazorpayCheckDialog
    from app.ui.windows.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(str(a)))
    win = MainWindow(AppContext(services=services, user=admin))
    win.navigate("settings")
    page = win.pages["settings"]
    assert page.rzp_status.text() == "Not connected." and page.rzp_check.isHidden()
    page.rzp_key.setText(KEY)
    page.rzp_secret.setText(SECRET)
    page.connect_razorpay()
    assert page.rzp_status.text().startswith("Connected: TEST mode")
    assert page.rzp_secret.text() == "" and not page.rzp_check.isHidden()
    methods = [r["name"] for r in page.pm_table.model.rows]
    assert "Razorpay" in methods
    fake.make_payment(12345)
    dlg = RazorpayCheckDialog(page, win.ctx, datetime.now().date())
    assert dlg.load()
    assert dlg.table.model.rows[0]["invoice"].startswith("NOT RECORDED")
    assert "1 payment(s) NOT RECORDED" in dlg.summary.text()
    win.navigate("sales")
    assert not win.pages["sales"].rzp_btn.isHidden()
    monkeypatch.setattr("app.ui.pages.settings_page.confirm", lambda *a, **k: True)
    win.navigate("settings")
    page.disconnect_razorpay()
    assert page.rzp_status.text() == "Not connected."
    win.close()


def test_dialog_background_thread_path(qapp, services, admin, connected, monkeypatch):
    """The real threaded path: network calls run off the UI thread, results come back
    through a queued Qt signal."""
    from PySide6.QtWidgets import QApplication

    from app.ui.context import AppContext
    from app.ui.dialogs.razorpay_dialog import RazorpayDialog
    f = connected
    ctx = AppContext(services=services, user=admin)
    d = RazorpayDialog(None, ctx, D("75"), run_async=True)

    def wait(cond, secs=10):
        end = time.time() + secs
        while not cond() and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)
        assert cond()
    wait(lambda: d.timer.isActive())                 # QR created + image loaded in background
    assert not d.qr.pixmap().isNull() and f.qrs[d.collection.id]["payment_amount"] == 7500
    d._poll()
    wait(lambda: not d._busy)
    assert d.paid is None
    f.pay_qr(d.collection.id)
    d._poll()
    wait(lambda: d.paid is not None)
    assert d.result() == 1 and d.paid.amount == D("75.00")
    d.deleteLater()
