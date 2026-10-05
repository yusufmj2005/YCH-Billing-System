"""Runtime paths and environment configuration.

Mutable data never lives next to the executable (which may be in
``C:\\Program Files``). Everything is stored under a per-user data folder:

    %LOCALAPPDATA%\\BusinessPOS\\
        database\\   businesspos.db
        backups\\    automatic, manual and safety backups
        logs\\       rotating application logs
        attachments\\ logo and product images
        exports\\    generated invoices, reports, labels

``BUSINESSPOS_DATA_DIR`` overrides the location (used by tests and for
development so a developer never touches a production database).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config.constants import APP_ID, DB_FILENAME


def is_frozen() -> bool:
    """True when running from the PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory that holds bundled read-only resources (assets/)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def asset_path(*parts: str) -> Path:
    return resource_root().joinpath("assets", *parts)


def default_data_dir() -> Path:
    override = os.environ.get("BUSINESSPOS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_ID
    return Path.home() / "AppData" / "Local" / APP_ID


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def database_dir(self) -> Path:
        return self.root / "database"

    @property
    def database_file(self) -> Path:
        return self.database_dir / DB_FILENAME

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def attachments_dir(self) -> Path:
        return self.root / "attachments"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def ensure(self) -> "AppPaths":
        for d in (self.database_dir, self.backups_dir, self.logs_dir,
                  self.attachments_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self


def get_paths(root: Path | None = None) -> AppPaths:
    return AppPaths(root or default_data_dir()).ensure()
