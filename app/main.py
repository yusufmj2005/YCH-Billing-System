"""BusinessPOS entry point.

Startup: single-instance check -> logging -> open/upgrade database ->
optional daily backup -> setup wizard (first run) or login -> main window.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback

# Allow `python app/main.py` as well as `python -m app.main`.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config.constants import APP_ID, APP_MUTEX_NAME, APP_NAME, APP_VERSION
from app.config.settings import asset_path, get_paths
from app.utils.logging_setup import setup_logging

log = logging.getLogger("businesspos")


class IdleWatcher(QObject):
    """Signs the user out after a configurable period without input."""

    def __init__(self, minutes: int, on_idle):
        super().__init__()
        self.timer = QTimer(self, singleShot=True, timeout=on_idle)
        self.ms = minutes * 60_000
        if self.ms:
            self.timer.start(self.ms)

    def eventFilter(self, obj, event):
        if self.ms and event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress,
                                        QEvent.MouseMove, QEvent.Wheel):
            self.timer.start(self.ms)
        return False


class Controller:
    def __init__(self, app: QApplication, services):
        self.app = app
        self.services = services
        self.login = None
        self.main = None
        self.wizard = None
        self.idle = None
        self.user = None

    def start(self):
        if not self.services.settings.is_setup_completed() or not self.services.auth.has_users():
            from app.ui.windows.setup_wizard import SetupWizard
            self.wizard = SetupWizard(self.services)
            self.wizard.setup_done.connect(self.open_main)
            self.wizard.show()
        else:
            self.show_login()

    def show_login(self):
        from app.ui.windows.login_window import LoginWindow
        if self.login is None:
            self.login = LoginWindow(self.services)
            self.login.logged_in.connect(self.open_main)
        self.login.reset()
        self.login.showMaximized() if self.main is None else self.login.show()
        self.login.raise_()
        self.login.activateWindow()

    def open_main(self, user):
        from app.ui.context import AppContext
        from app.ui.windows.main_window import MainWindow
        self.user = user
        ctx = AppContext(services=self.services, user=user)
        self.main = MainWindow(ctx)
        self.main.logout_requested.connect(self.logout)
        icon = asset_path("icons", "app.ico")
        if icon.is_file():
            self.main.setWindowIcon(QIcon(str(icon)))
        self.main.showMaximized()
        if self.login:
            self.login.hide()
        minutes = int(self.services.settings.get("idle_logout_minutes") or 0)
        if self.idle:
            self.app.removeEventFilter(self.idle)
        self.idle = IdleWatcher(minutes, self._idle_logout)
        self.app.installEventFilter(self.idle)

    def _idle_logout(self):
        log.info("Signing out after inactivity")
        self.logout()

    def logout(self):
        if self.user is not None:
            try:
                self.services.auth.logout(self.user)
            except Exception:  # e.g. user no longer exists after a restore
                log.warning("Could not record logout", exc_info=True)
        self.user = None
        if self.idle:
            self.app.removeEventFilter(self.idle)
            self.idle = None
        main, self.main = self.main, None
        self.show_login()
        if main is not None:
            for w in QApplication.topLevelWidgets():
                if w is not main and w is not self.login and w.isWindow() and w.isVisible() \
                        and w.parent() is main:
                    w.close()
            main.close()
            main.deleteLater()


def _install_excepthook(app: QApplication):
    def hook(exc_type, exc, tb):
        log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type,
                                                                                    exc, tb)))
        try:
            QMessageBox.critical(None, APP_NAME,
                                 "An unexpected error occurred. The action may not have been "
                                 "completed; no partial transaction was saved.\n\n"
                                 "Details were written to the log file.")
        except Exception:
            pass
    sys.excepthook = hook


def main() -> int:
    if "--self-test" in sys.argv:
        from app.selftest import run
        return run()
    paths = get_paths()
    setup_logging(paths.logs_dir)
    log.info("Starting %s %s (frozen=%s)", APP_NAME, APP_VERSION, getattr(sys, "frozen", False))

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setApplicationVersion(APP_VERSION)
    icon = asset_path("icons", "app.ico")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
        except Exception:
            pass

    from app.ui.styles.theme import apply_theme
    apply_theme(app)
    _install_excepthook(app)

    from app.utils.single_instance import acquire
    if not acquire(APP_MUTEX_NAME):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME} is already running.")
        return 0

    from app.bootstrap import build_services
    from app.database.migrations import SchemaError
    try:
        services = build_services(paths)
    except SchemaError as exc:
        log.error("Schema error: %s", exc)
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    except Exception:
        log.exception("Database initialisation failed")
        QMessageBox.critical(None, APP_NAME,
                             "The business database could not be opened. Please contact your "
                             "administrator. Details were written to the log file.")
        return 1

    try:
        if services.settings.is_setup_completed() and services.settings.get("auto_backup_on_start"):
            warning = services.backup.run_automatic(services.settings.get_all())
            if warning:
                QMessageBox.warning(None, f"{APP_NAME} - backup copy", warning)
    except Exception:
        log.exception("Automatic backup failed")

    controller = Controller(app, services)
    controller.start()
    code = app.exec()
    try:
        if services.settings.is_setup_completed() and services.settings.get("backup_on_exit"):
            services.backup.run_automatic(services.settings.get_all(), on_exit=True)
    except Exception:
        log.exception("Backup on exit failed")
    services.db.dispose()
    log.info("Exited with code %s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
