"""Per-session UI context handed to every page."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from app.bootstrap import Services
from app.security.auth import CurrentUser
from app.utils.money import fmt_money


@dataclass
class AppContext:
    services: Services
    user: CurrentUser
    toast: Callable[[str], None] = field(default=lambda msg: None)
    navigate: Callable[[str], None] = field(default=lambda key: None)
    _settings: dict | None = None

    @property
    def settings(self) -> dict:
        if self._settings is None:
            self._settings = self.services.settings.get_all()
        return self._settings

    def reload_settings(self) -> None:
        self._settings = None

    def can(self, *perms: str) -> bool:
        return self.user.has(*perms)

    def money(self, value) -> str:
        return f"{self.settings.get('currency_symbol') or ''}{fmt_money(value)}"

    def export_path(self, *parts: str) -> Path:
        safe = [re.sub(r"[^A-Za-z0-9._ -]", "_", p) for p in parts]
        p = self.services.paths.exports_dir.joinpath(*safe)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def open_file(path: Path) -> bool:
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @staticmethod
    def open_folder(path: Path) -> None:
        if os.name == "nt":
            os.startfile(str(path))  # noqa: S606 - local folder only
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
