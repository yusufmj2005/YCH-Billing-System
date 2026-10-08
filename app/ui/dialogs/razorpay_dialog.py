"""Collect a payment through Razorpay and wait for Razorpay to confirm it."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from decimal import Decimal

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from app.payments.razorpay import LinkCollection, PaidResult, QrCollection, RazorpayError
from app.ui.dialogs.upi_dialog import qr_pixmap
from app.ui.widgets.common import button, handle_exception, label, show_info, show_error
from app.utils.money import fmt_money, money

POLL_MS = 3000
RUN_ASYNC = True          # tests switch this off to run Razorpay calls inline


@contextmanager
def busy():
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


class _Bridge(QObject):
    done = Signal(object, object, object)       # callback, result, error


class RazorpayDialog(QDialog):
    """``paid`` holds the confirmed :class:`PaidResult` after ``exec()`` returns 1."""

    def __init__(self, parent, ctx, amount: Decimal, *, phone: str = "", customer: str = "",
                 note: str = "", run_async: bool | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.amount = money(amount)
        self.paid: PaidResult | None = None
        self.client = ctx.services.razorpay.client()          # raises NotConnected
        self.run_async = RUN_ASYNC if run_async is None else run_async
        self.collection = None
        self._gen = 0
        self._busy = False
        self._finished = False
        s = ctx.settings
        self.shop = s.get("upi_payee_name") or s.get("business_name") or "Shop"
        self.note = note or "Bill"
        self.customer = customer
        self._bridge = _Bridge()
        self._bridge.done.connect(lambda cb, res, err: cb(res, err))

        self.setWindowTitle("Pay with Razorpay")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        lay.setSpacing(10)
        title = label(f"Pay ₹{fmt_money(self.amount)}", "PageTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        if self.client.test_mode:
            tm = label("TEST MODE: no real money moves. Use Razorpay's test payment details, "
                       "then void the test sale.", "Notice", wrap=True)
            lay.addWidget(tm)

        modes = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        for i, text in enumerate(("UPI QR", "Payment link (card, UPI, net banking)")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("variant", "pay")
            self.mode_group.addButton(b, i)
            modes.addWidget(b)
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idClicked.connect(self._switch)
        lay.addLayout(modes)

        self.phone_row = QHBoxLayout()
        self.phone = QLineEdit(phone)
        self.phone.setPlaceholderText("Customer mobile (optional): Razorpay sends the link by SMS")
        self.phone.setMaxLength(16)
        self.phone_row.addWidget(self.phone, 1)
        self.link_btn = button("Create link", "primary", lambda: self._start("link"))
        self.phone_row.addWidget(self.link_btn)
        lay.addLayout(self.phone_row)

        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setFixedSize(340, 360)          # Razorpay's QR image is a portrait card
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.link_lbl = label("", "Muted")
        self.link_lbl.setAlignment(Qt.AlignCenter)
        self.link_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.link_lbl)
        self.status = label("", "SectionTitle")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(52)
        lay.addWidget(self.status)
        lay.addWidget(label("The sale is recorded only after Razorpay confirms the payment. "
                            "Keep this window open until then.", "Faint", wrap=True))
        row = QHBoxLayout()
        self.existing_btn = button("Already paid? Enter payment ID…", "ghost", self._existing)
        row.addWidget(self.existing_btn)
        row.addStretch(1)
        cancel = button("Cancel", None, self.reject)
        row.addWidget(cancel)
        for b in (self.existing_btn, cancel, self.link_btn):
            b.setAutoDefault(False)         # Enter must never trigger these by accident
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)
        self._show_mode(0)
        self._fit()
        QTimer.singleShot(0, lambda: self._start("qr"))

    # ---- background work ----------------------------------------------------------
    def _run(self, fn, callback) -> None:
        if not self.run_async:
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001
                res, err = None, exc
            callback(res, err)
            return

        def work():
            try:
                res, err = fn(), None
            except Exception as exc:  # noqa: BLE001
                res, err = None, exc
            try:
                self._bridge.done.emit(callback, res, err)
            except RuntimeError:      # dialog already destroyed
                pass
        threading.Thread(target=work, daemon=True).start()

    def _fit(self) -> None:
        """Grow the window to fit wrapped text + QR (Qt windows don't do this on their own)."""
        w = max(self.width(), self.minimumWidth())
        h = self.layout().totalHeightForWidth(w)
        if h > 0:
            self.setMinimumHeight(h)
            if self.height() < h:
                self.resize(w, h)

    # ---- modes --------------------------------------------------------------------
    def _show_mode(self, mode: int) -> None:
        link = mode == 1
        self.phone.setVisible(link)
        self.link_btn.setVisible(link)
        self.link_lbl.setVisible(link)
        self._fit()

    def _switch(self, mode: int) -> None:
        if self._finished:
            return
        if not self._stop_current():
            self.mode_group.button(0 if mode else 1).setChecked(True)
            return
        self._show_mode(mode)
        self.qr.clear()
        self.link_lbl.setText("")
        if mode == 0:
            self._start("qr")
        else:
            self.status.setText("Enter the customer's mobile to send the link by SMS (optional), "
                                "then Create link.")
            self.link_btn.setFocus()

    def _start(self, kind: str) -> None:
        if self._finished:
            return
        if self.collection is not None and not self._stop_current():
            return
        self._gen += 1
        gen = self._gen
        try:
            if kind == "qr":
                coll = QrCollection(self.client, self.amount, shop=self.shop, note=self.note)
            else:
                coll = LinkCollection(self.client, self.amount, shop=self.shop, note=self.note,
                                      contact=self.phone.text(), customer=self.customer)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.collection = coll
        self.status.setText("Creating the Razorpay QR…" if kind == "qr" else
                            "Creating the payment link…")
        self.link_btn.setEnabled(False)

        def work():
            data = coll.start()
            if kind == "qr":
                try:
                    return data, self.client.fetch_image(data.get("image_url", ""))
                except RazorpayError:
                    try:
                        coll.cancel()
                    except RazorpayError:
                        pass
                    raise
            return data, None
        self._run(work, lambda res, err: self._started(gen, kind, res, err))

    def _started(self, gen: int, kind: str, res, err) -> None:
        if gen != self._gen or self._finished:
            return
        self.link_btn.setEnabled(True)
        if err is not None:
            self.collection = None
            msg = str(err) if isinstance(err, RazorpayError) else "Unexpected error."
            if kind == "qr" and isinstance(err, RazorpayError) and not err.network:
                msg += ("\n\nIf QR codes are not enabled on your Razorpay account, use "
                        "Payment link instead.")
            self.status.setText("")
            show_error(self, msg)
            return
        data, image = res
        if kind == "qr":
            pm = QPixmap()
            pm.loadFromData(image)
            self.qr.setPixmap(pm.scaled(340, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.status.setText("Ask the customer to scan with any UPI app. Waiting for "
                                "payment…")
        else:
            url = data["short_url"]
            self.qr.setPixmap(qr_pixmap(url, 300))
            self.link_lbl.setText(url)
            sent = " Link sent by SMS." if self.collection.contact else ""
            self.status.setText(f"Customer scans this code (or opens the SMS link) and pays by "
                                f"UPI, card or net banking.{sent} Waiting for payment…")
        self._fit()
        self.timer.start()

    # ---- polling ------------------------------------------------------------------
    def _poll(self) -> None:
        coll = self.collection
        if self._busy or coll is None or coll.id is None or self._finished:
            return
        self._busy = True
        gen = self._gen
        self._run(coll.check, lambda res, err: self._polled(gen, res, err))

    def _polled(self, gen: int, res, err) -> None:
        self._busy = False
        if gen != self._gen or self._finished:
            return
        if err is not None:
            if isinstance(err, RazorpayError) and err.network:
                self.status.setText("Connection problem; still checking for the payment…")
                return
            self.timer.stop()
            show_error(self, str(err) if isinstance(err, RazorpayError) else "Unexpected error.")
            return
        if res is not None:
            self._paid(res)

    def _paid(self, res: PaidResult) -> None:
        self._finished = True
        self.timer.stop()
        self.paid = res
        self.status.setText(f"Paid ✓  {res.payment_id}")
        self.ctx.toast(f"Razorpay payment received: ₹{fmt_money(res.amount)}")
        super().accept()

    # ---- stopping -----------------------------------------------------------------
    def _stop_current(self) -> bool:
        """Close the open QR/link. Returns False when the customer has just paid (the
        dialog then finishes with that payment) or it could not be closed."""
        coll, self.collection = self.collection, None
        self.timer.stop()
        self._gen += 1
        if coll is None or coll.id is None:
            return True
        try:
            with busy():
                late = coll.cancel()
        except RazorpayError as exc:
            self.collection = coll
            self.timer.start()
            show_error(self, f"{exc}\n\nThe current {'QR' if coll.kind == 'qr' else 'link'} "
                             "is still open, so it was not changed.")
            return False
        if late is not None:
            show_info(self, "The customer has just paid. The payment is recorded.")
            self._paid(late)
            return False
        return True

    def reject(self) -> None:
        if self._finished:
            return super().reject()
        coll = self.collection
        if coll is not None and coll.id is not None:
            self.collection = None
            self.timer.stop()
            self._gen += 1
            try:
                with busy():
                    late = coll.cancel()
            except RazorpayError:
                show_error(self, "Could not reach Razorpay to close this payment request. It "
                                 "closes by itself shortly. If the customer still pays, use "
                                 "Already paid? Enter payment ID, or Check Razorpay payments "
                                 "in Settings › Payments.")
                late = None
            if late is not None:
                show_info(self, "The customer has just paid. The payment is recorded.")
                self._paid(late)
                return
        self._finished = True
        super().reject()

    def _existing(self) -> None:
        pid, ok = QInputDialog.getText(self, "Already paid", "Razorpay payment ID (pay_…), from "
                                       "the Razorpay Dashboard or the customer's receipt:")
        if not ok or not pid.strip():
            return
        if not self._stop_current():
            return
        self.qr.clear()
        self.link_lbl.setText("")
        self.status.setText("Choose UPI QR or Payment link to show a new code.")
        try:
            with busy():
                res = self.ctx.services.razorpay.existing_payment(self.ctx.user, pid,
                                                                  self.amount)
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self._paid(res)
