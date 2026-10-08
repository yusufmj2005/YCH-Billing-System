"""Packaged-build self test: ``BusinessPOS.exe --self-test``.

Runs in a temporary folder (never touches business data) and exercises the
bundled dependencies: SQLite + migrations, bcrypt, the sale transaction,
ReportLab PDF + barcode generation and QtPdf rendering. Writes a report to
``%TEMP%\\BusinessPOS-selftest.log`` and returns exit code 0 on success.
"""
from __future__ import annotations

import os
import tempfile
import traceback
from decimal import Decimal
from pathlib import Path


def run() -> int:
    log_path = Path(tempfile.gettempdir()) / "BusinessPOS-selftest.log"
    lines = []
    try:
        with tempfile.TemporaryDirectory(prefix="bpos-selftest-",
                                         ignore_cleanup_errors=True) as tmp:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from app.bootstrap import build_services
            from app.config.constants import PaymentKind
            from app.config.settings import AppPaths
            from app.printing.invoice_pdf import build_invoice_pdf
            from app.printing.label_pdf import LABEL_LAYOUTS, build_labels_pdf
            from app.services.sales_service import PaymentRequest, SaleLineRequest, SaleRequest

            paths = AppPaths(Path(tmp)).ensure()
            svc = build_services(paths)
            lines.append("database: ok")
            pw = "SelfTest-Pass-1"
            admin = svc.auth.complete_setup({
                "business_name": "Self test", "admin_username": "selftest",
                "admin_password": pw, "admin_password_confirm": pw, "invoice_prefix": "ST-",
                "tax_rates": [{"name": "T", "rate": "10"}]})
            svc.auth.login("selftest", pw)
            lines.append("auth: ok")
            tax = svc.catalog.list_tax_rates()[0]["id"]
            pid = svc.catalog.create_product(admin, {
                "name": "Self test item", "selling_price": "110", "unit": "pcs",
                "tax_rate_id": tax, "price_includes_tax": True, "opening_stock": "3",
                "barcode": "2000000000008"})
            cash = next(m["id"] for m in svc.payment_methods.list() if m["kind"] == PaymentKind.CASH)
            res = svc.sales.create_sale(admin, SaleRequest(
                lines=[SaleLineRequest(pid, Decimal(1))],
                payments=[PaymentRequest(cash, Decimal("110"))]))
            assert res["invoice_no"] == "ST-000001", res
            assert svc.inventory.verify_ledger() == []
            lines.append("sale transaction: ok")
            sale = svc.sales.get_sale(admin, res["sale_id"])
            pdf = build_invoice_pdf(sale, svc.settings.get_all(), paths.exports_dir / "t.pdf")
            build_labels_pdf([{"name": "x", "barcode": "2000000000008", "price": 1}],
                             paths.exports_dir / "l.pdf", list(LABEL_LAYOUTS)[0], {})
            lines.append("pdf + barcode: ok")
            svc.backup.create_backup(admin)
            lines.append("backup: ok")
            # encryption library bundled and working (AES-GCM + scrypt)
            svc.backup.set_backup_password(admin, "SelfTest-Backup-1", "SelfTest-Backup-1")
            enc = svc.backup.create_backup(admin)
            assert enc.name.endswith(".db.enc"), enc
            assert svc.backup.validate_backup(enc, "SelfTest-Backup-1")["encrypted"]
            lines.append("encrypted backup: ok")
            from app.payments.upi import qr_matrix, upi_uri
            assert len(qr_matrix(upi_uri("selftest@upi", "Self test", "1"))) >= 21
            lines.append("upi qr: ok")
            # Razorpay: secret protection (Windows DPAPI), HTTPS stack, client + service
            from app.security import secret_store
            assert secret_store.unprotect(secret_store.protect("SelfTestSecret1")) \
                == "SelfTestSecret1"
            from app.payments.razorpay import tls_context
            assert tls_context().cert_store_stats()["x509_ca"] > 100     # certifi bundled
            import app.ui.dialogs.razorpay_check_dialog  # noqa: F401
            import app.ui.dialogs.razorpay_dialog  # noqa: F401
            import json as _json
            svc.razorpay.transport = lambda m, u, h, b, t: (200, _json.dumps(
                {"entity": "collection", "items": []}).encode())
            assert svc.razorpay.connect(admin, "rzp_test_SelfTest0001",
                                        "SelfTestSecret0001")["connected"]
            assert svc.razorpay.method()["is_active"]
            svc.razorpay.disconnect(admin)
            lines.append("razorpay: ok")

            from PySide6.QtCore import QSize
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtPrintSupport import QPrinterInfo  # noqa: F401
            app = QGuiApplication.instance() or QGuiApplication([])
            from app.printing.printer import load_pdf
            doc, _buf = load_pdf(pdf)
            assert doc.pageCount() == 1
            img = doc.render(0, QSize(200, 280))
            assert not img.isNull()
            doc.close()
            lines.append("qt pdf rendering: ok")
            svc.db.dispose()
            del app
        lines.append("RESULT: PASS")
        code = 0
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("RESULT: FAIL")
        code = 1
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return code
