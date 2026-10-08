"""Backup password: encrypted backups, restore anywhere with the password."""
from pathlib import Path

import pytest

from app.backup import crypto
from app.bootstrap import build_services
from app.config.settings import AppPaths
from app.services.errors import PermissionDenied, ValidationError
from tests.conftest import ADMIN_PASSWORD

PW = "Backup-Secret-42"


# ---- the crypto primitives ----------------------------------------------------------
def test_round_trip_and_wrong_password():
    salt, key = crypto.new_key(PW)
    blob = crypto.encrypt(b"business data", key, salt)
    assert blob.startswith(crypto.MAGIC) and b"business data" not in blob
    assert crypto.decrypt(blob, key=key) == b"business data"
    assert crypto.decrypt(blob, password=PW) == b"business data"
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(blob, password="Wrong-Pass-1")
    with pytest.raises(crypto.PasswordRequired):
        crypto.decrypt(blob)


@pytest.mark.parametrize("pos", [10, 30, -1])          # salt, nonce/body, tag
def test_tampering_is_detected(pos):
    salt, key = crypto.new_key(PW)
    blob = bytearray(crypto.encrypt(b"x" * 100, key, salt))
    blob[pos] ^= 1
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(bytes(blob), password=PW)


def test_each_backup_uses_a_fresh_nonce():
    salt, key = crypto.new_key(PW)
    assert crypto.encrypt(b"same", key, salt) != crypto.encrypt(b"same", key, salt)


# ---- service ------------------------------------------------------------------------
def _scratch_files(services):
    return list(services.db.db_file.parent.glob(".bpos-*.tmp"))


def test_set_password_rules(services, admin):
    with pytest.raises(ValidationError, match="do not match"):
        services.backup.set_backup_password(admin, PW, PW + "x")
    with pytest.raises(ValidationError):
        services.backup.set_backup_password(admin, "short", "short")
    cashier = next(r["id"] for r in services.users.list_roles(admin) if r["name"] == "Cashier")
    services.users.create_user(admin, {"username": "cashier", "password": "Cashier-123",
                                       "role_id": cashier, "must_change_password": False})
    with pytest.raises(PermissionDenied):
        services.backup.set_backup_password(services.auth.login("cashier", "Cashier-123"),
                                            PW, PW)
    assert not services.backup.encryption_enabled()


def test_encrypted_backup_contains_no_readable_data(services, admin):
    services.backup.set_backup_password(admin, PW, PW)
    assert services.backup.encryption_enabled()
    target = services.backup.create_backup(admin)
    assert target.name.endswith(".db.enc")
    raw = target.read_bytes()
    assert raw.startswith(crypto.MAGIC)
    assert b"SQLite format 3" not in raw and b"Test Business" not in raw
    info = services.backup.validate_backup(target)              # this PC: no password needed
    assert info["encrypted"] and info["business_name"] == "Test Business"
    row = next(b for b in services.backup.list_backups() if b["name"] == target.name)
    assert row["encrypted"] and row["kind"] == "manual"
    assert _scratch_files(services) == []                         # no plaintext left behind


def test_secret_never_exposed_in_settings(services, admin):
    services.backup.set_backup_password(admin, PW, PW)
    assert not any(k.startswith("secret_") for k in services.settings.get_all())


def test_restore_on_another_pc_needs_the_password(services, admin, make_product, tmp_path):
    make_product(name="Merino Red")
    services.backup.set_backup_password(admin, PW, PW)
    backup = services.backup.create_backup(admin)

    other = build_services(AppPaths(tmp_path / "other-pc").ensure())     # fresh install
    try:
        boss = other.auth.complete_setup({
            "business_name": "Temporary", "admin_username": "newadmin",
            "admin_password": "New-Admin-123", "admin_password_confirm": "New-Admin-123"})
        with pytest.raises(crypto.PasswordRequired):
            other.backup.validate_backup(backup)
        with pytest.raises(crypto.WrongPassword):
            other.backup.restore(boss, backup, "Wrong-Pass-1")
        assert other.backup.validate_backup(backup, PW)["business_name"] == "Test Business"
        other.backup.restore(boss, backup, PW)
        cu = other.auth.login("admin", ADMIN_PASSWORD)              # the shop's own users
        assert [p["name"] for p in other.catalog.list_products(cu)[0]] == ["Merino Red"]
        assert other.settings.get("business_name") == "Test Business"
        assert _scratch_files(other) == []
    finally:
        other.db.dispose()


def test_restore_keeps_this_pcs_backup_password(services, admin):
    plain_backup = services.backup.create_backup(admin)             # before any password
    assert plain_backup.suffix == ".db"
    services.backup.set_backup_password(admin, PW, PW)
    services.backup.restore(admin, plain_backup)                    # old unencrypted backup
    assert services.backup.encryption_enabled()                     # still protected
    cu = services.auth.login("admin", ADMIN_PASSWORD)
    assert services.backup.create_backup(cu).name.endswith(".db.enc")


def test_remove_password(services, admin, tmp_path):
    services.backup.set_backup_password(admin, PW, PW)
    enc = services.backup.create_backup(admin)
    services.backup.remove_backup_password(admin)
    assert services.backup.create_backup(admin).suffix == ".db"
    with pytest.raises(crypto.PasswordRequired):                    # key gone from this PC
        services.backup.validate_backup(enc)
    assert services.backup.validate_backup(enc, PW)["encrypted"]


def test_automatic_backup_and_second_copy_are_encrypted(services, admin, tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    services.settings.update(admin, {"backup_copy_folder": str(usb)})
    services.backup.set_backup_password(admin, PW, PW)
    assert services.backup.run_automatic(services.settings.get_all(), on_exit=True) is None
    local = [b for b in services.backup.list_backups() if b["kind"] == "auto"]
    copies = services.backup.list_backups(usb)
    assert len(local) == len(copies) == 1 and copies[0]["encrypted"]
    assert Path(copies[0]["path"]).read_bytes() == Path(local[0]["path"]).read_bytes()
    assert not list(usb.glob(".*.tmp"))


# ---- UI --------------------------------------------------------------------------
def test_restore_screen_asks_for_password(services, admin, make_product, monkeypatch):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from app.ui.context import AppContext
    from app.ui.windows.main_window import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    make_product(name="Before backup")
    services.backup.set_backup_password(admin, PW, PW)
    backup = services.backup.create_backup(admin)
    services.backup.remove_backup_password(admin)      # as if restoring on another PC
    make_product(name="After backup")

    answers = iter([("Wrong-Pass-1", True), (PW, True), ("RESTORE", True)])
    prompts = []

    def fake_get_text(parent, title, text, *a, **k):
        prompts.append(text)
        return next(answers)
    monkeypatch.setattr(QInputDialog, "getText", fake_get_text)

    win = MainWindow(AppContext(services=services, user=admin))
    win.navigate("backup")
    page = win.pages["backup"]
    page.restore({"path": str(backup), "name": backup.name})
    assert "protected with a backup password" in prompts[0]
    assert "wrong" in prompts[1].lower()
    assert "RESTORE" in prompts[2]
    cu = services.auth.login("admin", ADMIN_PASSWORD)
    assert [p["name"] for p in services.catalog.list_products(cu)[0]] == ["Before backup"]
    win.close()


def test_settings_page_shows_password_status(services, admin):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from app.ui.context import AppContext
    from app.ui.windows.main_window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow(AppContext(services=services, user=admin))
    win.navigate("settings")
    page = win.pages["settings"]
    assert page.enc_status.text() == "Off" and page.enc_remove.isHidden()
    services.backup.set_backup_password(admin, PW, PW)
    page.on_show()
    assert page.enc_status.text().startswith("On") and not page.enc_remove.isHidden()
    win.close()
