from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QMessageBox

from app.backup.crypto import PasswordRequired, WrongPassword

from app.config.constants import Perm
from app.reports.base import Col
from app.ui.pages.base import Page
from app.ui.widgets.common import Card, button, label, show_info, ui_action
from app.ui.widgets.table import DataTable


class BackupPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        row = QHBoxLayout()
        if ctx.can(Perm.BACKUP_DATABASE):
            c1 = Card()
            c1.lay.addWidget(label("Back up", "SectionTitle"))
            c1.lay.addWidget(label("Creates a complete, verified copy of all business data "
                                   "(sales, stock, customers, settings, users and audit log). "
                                   "Keep copies on a USB drive or another computer.", "Muted",
                                   wrap=True))
            b = QHBoxLayout()
            b.addWidget(button("Back up now", "primary", self.backup_default))
            b.addWidget(button("Back up to folder…", None, self.backup_to))
            b.addStretch(1)
            c1.lay.addLayout(b)
            row.addWidget(c1, 1)
        if ctx.can(Perm.RESTORE_DATABASE):
            c2 = Card()
            c2.lay.addWidget(label("Restore", "SectionTitle"))
            c2.lay.addWidget(label("Replaces ALL current data with the contents of a backup "
                                   "file. A safety backup of the current data is made first so "
                                   "the restore can be undone.", "Muted", wrap=True))
            b2 = QHBoxLayout()
            b2.addWidget(button("Restore from file…", "danger", self.restore_file))
            b2.addWidget(button("Restore selected", "danger",
                                lambda: self.restore(self.table.selected())))
            b2.addStretch(1)
            c2.lay.addLayout(b2)
            row.addWidget(c2, 1)
        self.root.addLayout(row)
        head = QHBoxLayout()
        head.addWidget(label("Backups in the default folder", "SectionTitle"))
        head.addStretch(1)
        head.addWidget(button("Open backup folder", "ghost", lambda: ctx.open_folder(
            ctx.services.paths.backups_dir)))
        self.root.addLayout(head)
        self.table = DataTable([Col("name", "File"), Col("kind", "Type"),
                                Col("enc", "Encrypted"), Col("modified", "Created", "datetime"),
                                Col("size_txt", "Size")], stretch="name")
        self.root.addWidget(self.table, 1)
        self.root.addWidget(label("Automatic backups and the backup password are set in "
                                  "Settings › Security & backup.", "Faint"))

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        rows = self.ctx.services.backup.list_backups()
        for r in rows:
            r["size_txt"] = f"{r['size'] / 1024:,.0f} KB"
            r["enc"] = "Yes" if r["encrypted"] else "No"
        self.table.set_rows(rows)

    @ui_action
    def backup_default(self):
        path = self.ctx.services.backup.create_backup(self.ctx.user)
        self.ctx.toast(f"Backup created: {path.name}")
        self.load()

    @ui_action
    def backup_to(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose backup folder")
        if folder:
            path = self.ctx.services.backup.create_backup(self.ctx.user, Path(folder))
            show_info(self, f"Backup created and verified:\n{path}")
            self.load()

    @ui_action
    def restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose backup file",
                                              str(self.ctx.services.paths.backups_dir),
                                              "BusinessPOS backups (*.db *.db.enc)")
        if path:
            self.restore({"path": path, "name": Path(path).name})

    @ui_action
    def restore(self, row):
        if not row:
            show_info(self, "Select a backup in the list first.")
            return
        password = None
        while True:
            try:
                info = self.ctx.services.backup.validate_backup(Path(row["path"]), password)
                break
            except (PasswordRequired, WrongPassword) as exc:
                prompt = (f"{exc}\n\nEnter the backup password for {row['name']}:"
                          if isinstance(exc, WrongPassword) and password else
                          f"{row['name']} is protected with a backup password.\n\n"
                          "Enter the backup password:")
                password, ok = QInputDialog.getText(self, "Backup password", prompt,
                                                    QLineEdit.Password)
                if not ok:
                    return
        c = info["counts"]
        msg = (f"Backup: {row['name']}\nBusiness: {info['business_name'] or '—'}\n"
               f"Contains {c['sales']} sales, {c['products']} products, {c['customers']} "
               f"customers, {c['purchases']} purchases, {c['expenses']} expenses, "
               f"{c['users']} users.\nLast sale: {info['last_sale'] or '—'}\n\n"
               "ALL current data will be replaced by this backup. A safety backup of the "
               "current data will be created first.\n\nType RESTORE to confirm:")
        text, ok = QInputDialog.getText(self, "Confirm restore", msg)
        if not ok:
            return
        if text.strip() != "RESTORE":
            show_info(self, "Restore cancelled (confirmation text did not match).")
            return
        safety = self.ctx.services.backup.restore(self.ctx.user, Path(row["path"]), password)
        QMessageBox.information(
            self, "Restore complete",
            f"The data was restored from {row['name']}.\n\nSafety backup of the previous data: "
            f"{safety.name}\n\nYou will now be signed out. Please sign in again.")
        win = self.window()
        if hasattr(win, "logout_requested"):
            win.logout_requested.emit()
