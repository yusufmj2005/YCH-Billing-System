"""Database backup, validation and restore.

Backups use SQLite's online backup API, which produces a consistent copy
even while the application is running. Before any restore a *safety backup*
of the current database is written so the restore itself can be undone.

With a backup password set, backups are written encrypted (``*.db.enc``,
see ``app/backup/crypto.py``). The derived key is kept in the live database so
automatic backups need no typing; a backup can be restored on any PC with
the password.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.config.constants import DB_IDENTIFIER, Perm, SCHEMA_VERSION
from app.config.settings import AppPaths
from app.backup import crypto
from app.database.database import Database
from app.models import Setting
from app.security.auth import CurrentUser, require
from app.security.passwords import validate_password_strength
from app.services import audit_service
from app.services.errors import BusinessError, ValidationError

log = logging.getLogger(__name__)

BACKUP_GLOBS = ("BusinessPOS-*.db", "BusinessPOS-*.db.enc")
_SALT_KEY, _KEY_KEY = "secret_backup_salt", "secret_backup_key"


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
        enc = self._stored_key()
        ext = ".db.enc" if enc else ".db"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = dest_dir / f"BusinessPOS-{kind}-{stamp}{ext}"
        n = 1
        while target.exists():
            target = dest_dir / f"BusinessPOS-{kind}-{stamp}-{n}{ext}"
            n += 1
        tmp = dest_dir / f".{target.name}.tmp"
        plain = self._scratch_file() if enc else tmp
        try:
            _copy_db(self.db.db_file, plain)
            self._validate_plain(plain)
            if enc:
                salt, key = enc
                data = plain.read_bytes()
                tmp.write_bytes(crypto.encrypt(data, key, salt))
                if crypto.decrypt(tmp.read_bytes(), key=key) != data:   # read back and verify
                    raise OSError("encrypted backup did not verify")
            os.replace(tmp, target)
        except ValidationError:
            tmp.unlink(missing_ok=True)
            raise
        except (OSError, sqlite3.Error, BusinessError) as exc:
            tmp.unlink(missing_ok=True)
            log.exception("Backup failed")
            raise BusinessError("The backup could not be written. Check that the location is "
                                "available and has free space.") from exc
        finally:
            if enc:
                plain.unlink(missing_ok=True)
        log.info("Backup created (%s): %s", kind, target)
        try:
            with self.db.session() as s:
                audit_service.record(s, actor, "BACKUP_CREATED", "database", None,
                                     {"kind": kind, "file": target.name,
                                      "encrypted": bool(enc)},
                                     username="system" if actor is None else None)
        except Exception:  # audit failure must not hide a successful backup
            log.exception("Could not audit backup")
        return target

    # ---- validate ------------------------------------------------------------------
    def validate_backup(self, path: Path, password: str | None = None) -> dict:
        """Check a backup and summarise its contents. Encrypted backups made with
        this PC's current password open automatically; others need ``password``
        (raises crypto.PasswordRequired / crypto.WrongPassword)."""
        path = Path(path)
        if not path.is_file():
            raise ValidationError("The selected backup file does not exist.")
        if not crypto.is_encrypted(path):
            return {**self._validate_plain(path), "encrypted": False}
        plain = self._decrypt_to_scratch(path, password)
        try:
            info = self._validate_plain(plain)
        finally:
            plain.unlink(missing_ok=True)
        return {**info, "encrypted": True, "size": path.stat().st_size}

    def _validate_plain(self, path: Path) -> dict:
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
    def restore(self, actor: CurrentUser, path: Path, password: str | None = None) -> Path:
        """Replace the live database with ``path``. Returns the safety backup."""
        require(actor, Perm.RESTORE_DATABASE)
        path = Path(path)
        if not path.is_file():
            raise ValidationError("The selected backup file does not exist.")
        if path.resolve() == self.db.db_file.resolve():
            raise ValidationError("You cannot restore the live database onto itself.")
        encrypted = crypto.is_encrypted(path)
        source = self._decrypt_to_scratch(path, password) if encrypted else path
        own_key = self._stored_key()      # the backup password belongs to this installation
        rollback = self._scratch_file()
        try:
            info = self._validate_plain(source)
            safety = self.create_backup(actor, kind="pre-restore")
            _copy_db(self.db.db_file, rollback)          # plain copy for an automatic undo
            self.db.dispose()
            try:
                _copy_db(source, self.db.db_file)
                self.db.reopen()
                if self._reinitialize:
                    self._reinitialize(self.db)
                self._write_key(own_key)        # keep this PC's backup password setting
            except Exception:
                log.exception("Restore failed; putting the previous data back")
                self.db.dispose()
                _copy_db(rollback, self.db.db_file)
                self.db.reopen()
                raise BusinessError("The restore failed and the previous data was kept. "
                                    "See the log file for details.") from None
        finally:
            rollback.unlink(missing_ok=True)
            if encrypted:
                source.unlink(missing_ok=True)
        with self.db.session() as s:
            audit_service.record(s, None, "DATABASE_RESTORED", "database", None,
                                 {"from_file": path.name, "safety_backup": safety.name,
                                  "encrypted": encrypted,
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
        files = {p for pattern in BACKUP_GLOBS for p in folder.glob(pattern)}
        out = []
        for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            st = p.stat()
            kind = p.name.split("-")[1] if p.name.count("-") >= 2 else ""
            out.append({"path": str(p), "name": p.name, "kind": kind, "size": st.st_size,
                        "encrypted": p.name.endswith(".enc"),
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
        tmp = dest_dir / f".{target.name}.tmp"
        try:
            if crypto.is_encrypted(Path(backup)):
                shutil.copyfile(backup, tmp)                 # already verified when created
                if _sha256(tmp) != _sha256(Path(backup)):
                    raise OSError("copy did not verify")
            else:
                _copy_db(Path(backup), tmp)
                self._validate_plain(tmp)
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
        if not folder:
            return None
        if target is None:          # today's backup already exists; still check the folder
            if Path(folder).is_dir():
                return None
            return (f"The second backup folder is not available:\n{folder}\n\n"
                    f"Connect the drive (or check the folder) so today's backups can be "
                    f"copied there, or change it in Settings \u203a Security & backup.")
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

    # ---- backup password -------------------------------------------------------------
    def encryption_enabled(self) -> bool:
        return self._stored_key() is not None

    def set_backup_password(self, actor: CurrentUser, password: str, confirm: str) -> None:
        """Encrypt all future backups. Existing backup files are not changed."""
        require(actor, Perm.MANAGE_SETTINGS, Perm.BACKUP_DATABASE)
        if password != confirm:
            raise ValidationError("The passwords do not match.")
        validate_password_strength(password)
        self._write_key(crypto.new_key(password), actor.id)
        with self.db.session() as s:
            audit_service.record(s, actor, "BACKUP_PASSWORD_SET", "settings", None, {})

    def _write_key(self, key: tuple[bytes, bytes] | None, actor_id: int | None = None) -> None:
        with self.db.session() as s:
            for k, raw in ((_SALT_KEY, key and key[0]), (_KEY_KEY, key and key[1])):
                row = s.get(Setting, k)
                if raw is None:
                    if row is not None:
                        s.delete(row)
                    continue
                value = json.dumps(base64.b64encode(raw).decode("ascii"))
                if row is None:
                    s.add(Setting(key=k, value=value, updated_by=actor_id))
                else:
                    row.value, row.updated_by = value, actor_id

    def remove_backup_password(self, actor: CurrentUser) -> None:
        """Future backups are written unencrypted; encrypted files keep their password."""
        require(actor, Perm.MANAGE_SETTINGS, Perm.BACKUP_DATABASE)
        self._write_key(None)
        with self.db.session() as s:
            audit_service.record(s, actor, "BACKUP_PASSWORD_REMOVED", "settings", None, {})

    def _stored_key(self) -> tuple[bytes, bytes] | None:
        with self.db.session() as s:
            salt, key = s.get(Setting, _SALT_KEY), s.get(Setting, _KEY_KEY)
            if salt is None or key is None:
                return None
            return (base64.b64decode(json.loads(salt.value)),
                    base64.b64decode(json.loads(key.value)))

    def _scratch_file(self) -> Path:
        """A private temporary file next to the live database (never in a copy folder)."""
        return self.db.db_file.parent / f".bpos-{uuid.uuid4().hex}.tmp"

    def _decrypt_to_scratch(self, path: Path, password: str | None) -> Path:
        blob = Path(path).read_bytes()
        stored = self._stored_key()
        if stored and crypto.salt_of(blob) == stored[0]:
            plain = crypto.decrypt(blob, key=stored[1])
        else:
            plain = crypto.decrypt(blob, password=password)
        out = self._scratch_file()
        out.write_bytes(plain)
        return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
