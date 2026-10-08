"""Database backup, validation and restore.

Backups use SQLite's online backup API, which produces a consistent copy
even while the application is running. Before any restore a *safety backup*
of the current database is written so the restore itself can be undone.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.config.constants import DB_IDENTIFIER, Perm, SCHEMA_VERSION
from app.config.settings import AppPaths
from app.database.database import Database
from app.security.auth import CurrentUser, require
from app.services import audit_service
from app.services.errors import BusinessError, ValidationError

log = logging.getLogger(__name__)

BACKUP_GLOB = "BusinessPOS-*.db"


def _ro_uri(path: Path) -> str:
    """Read-only SQLite URI. ``as_uri`` percent-encodes '#', '?' and '%' so
    folder names containing them are not misparsed as URI syntax."""
    return f"{Path(path).resolve().as_uri()}?mode=ro"


def _copy_db(src_path: Path, dst_path: Path) -> None:
    src = sqlite3.connect(_ro_uri(src_path), uri=True)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


class BackupService:
    def __init__(self, db: Database, paths: AppPaths,
                 reinitialize: Callable[[Database], None] | None = None):
        self.db = db
        self.paths = paths
        self._reinitialize = reinitialize

    # ---- create ------------------------------------------------------------------
    def create_backup(self, actor: CurrentUser | None, dest_dir: Path | None = None,
                      kind: str = "manual") -> Path:
        if kind == "manual":
            require(actor, Perm.BACKUP_DATABASE)
        dest_dir = Path(dest_dir) if dest_dir else self.paths.backups_dir
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BusinessError("The backup folder could not be created. "
                                "Please choose another location.") from exc
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = dest_dir / f"BusinessPOS-{kind}-{stamp}.db"
        n = 1
        while target.exists():
            target = dest_dir / f"BusinessPOS-{kind}-{stamp}-{n}.db"
            n += 1
        tmp = target.with_suffix(".tmp")
        try:
            _copy_db(self.db.db_file, tmp)
            self.validate_backup(tmp)
            os.replace(tmp, target)
        except ValidationError:
            tmp.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.Error) as exc:
            tmp.unlink(missing_ok=True)
            log.exception("Backup failed")
            raise BusinessError("The backup could not be written. Check that the location is "
                                "available and has free space.") from exc
        log.info("Backup created (%s): %s", kind, target)
        try:
            with self.db.session() as s:
                audit_service.record(s, actor, "BACKUP_CREATED", "database", None,
                                     {"kind": kind, "file": target.name},
                                     username="system" if actor is None else None)
        except Exception:  # audit failure must not hide a successful backup
            log.exception("Could not audit backup")
        return target

    # ---- validate ------------------------------------------------------------------
    def validate_backup(self, path: Path) -> dict:
        path = Path(path)
        if not path.is_file():
            raise ValidationError("The selected backup file does not exist.")
        try:
            con = sqlite3.connect(_ro_uri(path), uri=True)
        except sqlite3.Error:
            raise ValidationError("The selected file is not a valid BusinessPOS backup.") from None
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValidationError("The backup file is damaged (integrity check failed).")
            meta = dict(con.execute("SELECT key, value FROM app_meta").fetchall())
            if meta.get("identifier") != DB_IDENTIFIER:
                raise ValidationError("The selected file is not a BusinessPOS backup.")
            version = int(meta.get("schema_version", "0"))
            if version > SCHEMA_VERSION:
                raise ValidationError("This backup was made by a newer version of BusinessPOS. "
                                      "Please update the application first.")
            counts = {}
            for table in ("sales", "products", "customers", "purchases", "expenses", "users"):
                counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            business = con.execute(
                "SELECT value FROM business_settings WHERE key='business_name'").fetchone()
            last_sale = con.execute("SELECT MAX(created_at) FROM sales").fetchone()[0]
            try:
                business_name = json.loads(business[0]) if business else ""
            except ValueError:
                business_name = ""
            return {"schema_version": version, "counts": counts,
                    "business_name": business_name,
                    "last_sale": last_sale, "size": path.stat().st_size}
        except sqlite3.DatabaseError:
            raise ValidationError("The selected file is not a valid BusinessPOS backup.") from None
        finally:
            con.close()

    # ---- restore -------------------------------------------------------------------
    def restore(self, actor: CurrentUser, path: Path) -> Path:
        """Replace the live database with ``path``. Returns the safety backup."""
        require(actor, Perm.RESTORE_DATABASE)
        path = Path(path)
        info = self.validate_backup(path)
        if path.resolve() == self.db.db_file.resolve():
            raise ValidationError("You cannot restore the live database onto itself.")
        safety = self.create_backup(actor, kind="pre-restore")
        self.db.dispose()
        try:
            _copy_db(path, self.db.db_file)
            self.db.reopen()
            if self._reinitialize:
                self._reinitialize(self.db)
        except Exception:
            log.exception("Restore failed; rolling back to safety backup %s", safety)
            self.db.dispose()
            _copy_db(safety, self.db.db_file)
            self.db.reopen()
            raise BusinessError("The restore failed and the previous data was kept. "
                                "See the log file for details.") from None
        with self.db.session() as s:
            audit_service.record(s, None, "DATABASE_RESTORED", "database", None,
                                 {"from_file": path.name, "safety_backup": safety.name,
                                  "restored_by": actor.username,
                                  "backup_schema": info["schema_version"]},
                                 username=actor.username)
        log.info("Database restored from %s (safety backup %s)", path, safety)
        return safety

    # ---- housekeeping --------------------------------------------------------------
    def list_backups(self, folder: Path | None = None) -> list[dict]:
        folder = Path(folder) if folder else self.paths.backups_dir
        if not folder.is_dir():
            return []
        out = []
        for p in sorted(folder.glob(BACKUP_GLOB), key=lambda x: x.stat().st_mtime, reverse=True):
            st = p.stat()
            kind = p.stem.split("-")[1] if p.stem.count("-") >= 2 else ""
            out.append({"path": str(p), "name": p.name, "kind": kind, "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).replace(microsecond=0)})
        return out

    def prune_auto_backups(self, keep: int) -> int:
        autos = [b for b in self.list_backups() if b["kind"] == "auto"]
        removed = 0
        for b in autos[keep:]:
            try:
                Path(b["path"]).unlink()
                removed += 1
            except OSError:
                log.warning("Could not remove old automatic backup %s", b["path"])
        return removed

    def auto_backup_if_due(self, keep: int) -> Path | None:
        today = date.today().strftime("%Y%m%d")
        if any(b["kind"] == "auto" and today in b["name"] for b in self.list_backups()):
            return None
        target = self.create_backup(None, kind="auto")
        self.prune_auto_backups(keep)
        return target

    # ---- second copy (USB drive / cloud-synced folder) ----------------------------
    def copy_to_folder(self, backup: Path, folder: str | Path, keep: int) -> Path:
        """Copy ``backup`` into ``folder`` (verified), keeping the newest ``keep``
        automatic backups there. Raises BusinessError if the folder is unavailable."""
        dest_dir = Path(folder)
        if not dest_dir.is_dir():
            raise BusinessError(f"The backup copy folder {dest_dir} is not available.")
        target = dest_dir / Path(backup).name
        tmp = target.with_suffix(".tmp")
        try:
            _copy_db(Path(backup), tmp)
            self.validate_backup(tmp)
            os.replace(tmp, target)
        except (OSError, sqlite3.Error, ValidationError) as exc:
            tmp.unlink(missing_ok=True)
            raise BusinessError(f"The backup could not be copied to {dest_dir}.") from exc
        autos = [b for b in self.list_backups(dest_dir) if b["kind"] == "auto"]
        for b in autos[keep:]:
            try:
                Path(b["path"]).unlink()
            except OSError:
                log.warning("Could not remove old backup copy %s", b["path"])
        return target

    def run_automatic(self, settings: dict, *, on_exit: bool = False) -> str | None:
        """Automatic backup at start-up (once a day) or when the app closes
        (always, so the day's work is saved), then the optional second copy.
        Returns a user-facing warning when the second copy failed, else None."""
        keep = int(settings.get("backup_keep_count") or 30)
        if on_exit:
            target = self.create_backup(None, kind="auto")
            self.prune_auto_backups(keep)
        else:
            target = self.auto_backup_if_due(keep)
        folder = (settings.get("backup_copy_folder") or "").strip()
        if target is None or not folder:
            return None
        try:
            self.copy_to_folder(target, folder, keep)
            return None
        except BusinessError as exc:
            log.warning("Backup copy failed: %s", exc, exc_info=True)
            try:
                with self.db.session() as s:
                    audit_service.record(s, None, "BACKUP_COPY_FAILED", "database", None,
                                         {"folder": folder, "file": target.name},
                                         username="system")
            except Exception:
                log.exception("Could not audit backup copy failure")
            return (f"Today's backup was saved on this computer, but it could not be copied "
                    f"to:\n{folder}\n\nConnect the drive (or check the folder) and use "
                    f"Backup & Restore to make a copy, or change the folder in "
                    f"Settings \u203a Security & backup.")
