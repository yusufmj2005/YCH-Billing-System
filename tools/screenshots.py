"""DEVELOPMENT ONLY - render every page offscreen to PNG files for visual review.

    set BUSINESSPOS_DATA_DIR=<dev folder seeded by tools/demo_seed.py>
    python tools/screenshots.py <output folder>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                                     "Fonts"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.bootstrap import build_services  # noqa: E402
from app.config.settings import AppPaths  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.styles.theme import apply_theme  # noqa: E402
from app.ui.windows.main_window import NAVIGATION, MainWindow  # noqa: E402


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    apply_theme(app)
    svc = build_services(AppPaths(Path(os.environ["BUSINESSPOS_DATA_DIR"])).ensure())
    user = svc.auth.login("demo", "Demo-Pass-123")
    win = MainWindow(AppContext(services=svc, user=user))
    win.resize(1440, 860)
    win.show()
    only = sys.argv[2:] or None
    for _, items in NAVIGATION:
        for key, *_ in items:
            if only and key not in only:
                continue
            win.navigate(key)
            if key == "pos":
                pos = win.pages["pos"]
                for code in ("DEMO0000", "DEMO1001", "DEMO1001", "DEMO2002"):
                    pos.search.setText(code)
                    pos._search_enter()
                pos.search.setText("")
                pos._do_search()
                from app.services.sales_service import SaleLineRequest, SaleRequest
                from app.ui.dialogs.checkout_dialog import CheckoutDialog
                req = SaleRequest(lines=[SaleLineRequest(ln["product"]["id"], ln["qty"])
                                         for ln in pos.cart])
                dlg = CheckoutDialog(win, win.ctx, pos.compute(), req)
                dlg.show()
                for _ in range(3):
                    app.processEvents()
                dlg.grab().save(str(out / "checkout.png"))
                dlg.close()
            for _ in range(5):
                app.processEvents()
            win.grab().save(str(out / f"{key}.png"))
    from app.ui.windows.login_window import LoginWindow
    lw = LoginWindow(svc)
    lw.resize(1100, 700)
    lw.show()
    app.processEvents()
    lw.grab().save(str(out / "login.png"))
    from app.ui.windows.setup_wizard import SetupWizard
    wz = SetupWizard(svc)
    wz.show()
    for i in range(3):
        app.processEvents()
        wz.grab().save(str(out / f"wizard{i}.png"))
        wz.next() if i == 0 else None
        if i == 1:
            wz.business.name.setText("Example")
            wz.next()
    print("Saved screenshots to", out)


if __name__ == "__main__":
    main()
