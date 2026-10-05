"""Login screen."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

from app.bootstrap import Services
from app.config.constants import APP_NAME, APP_VERSION
from app.security.auth import CurrentUser
from app.services.errors import BusinessError
from app.ui.widgets.common import GENERIC_ERROR, button, label

import logging

log = logging.getLogger(__name__)


class LoginWindow(QWidget):
    logged_in = Signal(object)  # CurrentUser

    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.setWindowTitle(f"{APP_NAME} — Sign in")
        self.setObjectName("Page")
        self.resize(980, 640)
        settings = services.settings.get_all()

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("LoginCard")
        card.setFixedWidth(400)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 32, 36, 28)
        lay.setSpacing(10)

        logo_file = services.settings.logo_file()
        if logo_file:
            pm = QPixmap(str(logo_file))
            if not pm.isNull():
                lg = QLabel()
                lg.setPixmap(pm.scaledToHeight(56, Qt.SmoothTransformation))
                lg.setAlignment(Qt.AlignCenter)
                lay.addWidget(lg)
        name = settings.get("business_name") or APP_NAME
        title = label(name, "PageTitle")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        lay.addWidget(title)
        sub = label("Sign in to continue", "Muted")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(10)

        lay.addWidget(label("Username"))
        self.username = QLineEdit()
        self.username.setPlaceholderText("Enter your username")
        lay.addWidget(self.username)
        lay.addWidget(label("Password"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Enter your password")
        lay.addWidget(self.password)
        self.error = label("", "ErrorText", wrap=True)
        self.error.hide()
        lay.addWidget(self.error)
        lay.addSpacing(6)
        self.submit = button("Sign in", "primary", self._login)
        self.submit.setMinimumHeight(38)
        lay.addWidget(self.submit)
        lay.addSpacing(8)
        foot = label(f"{APP_NAME} {APP_VERSION}", "Faint")
        foot.setAlignment(Qt.AlignCenter)
        lay.addWidget(foot)

        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._login)
        self.username.setFocus()

    def reset(self) -> None:
        self.password.clear()
        self.error.hide()
        self.username.setFocus()

    def _login(self) -> None:
        self.error.hide()
        try:
            user: CurrentUser = self.services.auth.login(self.username.text(), self.password.text())
        except BusinessError as exc:
            self.error.setText(str(exc))
            self.error.show()
            self.password.selectAll()
            self.password.setFocus()
            return
        except Exception:
            log.exception("Login failed unexpectedly")
            self.error.setText(GENERIC_ERROR)
            self.error.show()
            return
        self.password.clear()
        if self.services.auth.must_change_password(user):
            from app.ui.dialogs.password_dialogs import ChangePasswordDialog
            dlg = ChangePasswordDialog(self, self.services, user, forced=True)
            if dlg.exec() != QDialog.Accepted:
                return
        self.logged_in.emit(user)
