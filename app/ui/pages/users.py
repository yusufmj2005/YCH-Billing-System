from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from app.config.constants import Perm
from app.reports.base import Col
from app.services.errors import ValidationError
from app.ui.dialogs.password_dialogs import PASSWORD_HELP
from app.ui.pages.base import Page
from app.ui.styles.theme import C
from app.ui.widgets.common import (button, confirm, handle_exception, label, show_info,
                                   ui_action)
from app.ui.widgets.forms import Field, FormDialog
from app.ui.widgets.table import DataTable


class RoleDialog(QDialog):
    def __init__(self, parent, ctx, role: dict | None, permissions: list[dict]):
        super().__init__(parent)
        self.ctx = ctx
        self.role = role
        self.setWindowTitle("Edit role" if role else "New role")
        self.resize(560, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        f = QFormLayout()
        self.name = QLineEdit(role["name"] if role else "")
        self.desc = QLineEdit(role["description"] if role else "")
        f.addRow("Role name *", self.name)
        f.addRow("Description", self.desc)
        lay.addLayout(f)
        locked = bool(role and role["is_system"])
        if locked:
            lay.addWidget(label("The Administrator role always has every permission and cannot "
                                "be renamed.", "Notice", wrap=True))
            self.name.setEnabled(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        groups = {}
        current = set(role["permissions"]) if role else set()
        for p in permissions:
            g = groups.get(p["group"])
            if g is None:
                g = QTreeWidgetItem([p["group"]])
                g.setFlags(g.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                self.tree.addTopLevelItem(g)
                groups[p["group"]] = g
            it = QTreeWidgetItem([f"{p['name']}"])
            it.setToolTip(0, p["code"])
            it.setData(0, Qt.UserRole, p["code"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if (locked or p["code"] in current) else Qt.Unchecked)
            g.addChild(it)
        self.tree.expandAll()
        self.tree.setEnabled(not locked)
        lay.addWidget(self.tree, 1)
        lay.addWidget(label("Permissions are enforced by the application's business logic, not "
                            "only by hiding menu items. Changes apply at the user's next sign-in.",
                            "Faint", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def codes(self) -> list[str]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                it = g.child(j)
                if it.checkState(0) == Qt.Checked:
                    out.append(it.data(0, Qt.UserRole))
        return out

    def _save(self):
        try:
            self.ctx.services.users.save_role(self.ctx.user, self.role["id"] if self.role else None,
                                              self.name.text(), self.desc.text(), self.codes())
        except Exception as exc:  # noqa: BLE001
            handle_exception(self, exc)
            return
        self.accept()


class UsersPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)
        if ctx.can(Perm.MANAGE_USERS):
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(0, 8, 0, 0)
            bar = QHBoxLayout()
            bar.addWidget(label("Each person should have their own account so the audit log "
                                "shows who did what.", "Muted"), 1)
            bar.addWidget(button("New user", "primary", self.new_user))
            l.addLayout(bar)
            self.users = DataTable([Col("username", "Username"), Col("full_name", "Full name"),
                                    Col("role", "Role"), Col("status", "Status"),
                                    Col("last_login_at", "Last sign-in", "datetime")],
                                   stretch="full_name")
            self.users.set_row_color(lambda r: None if r["is_active"] else C["faint"])
            self.users.activated.connect(self.edit_user)
            l.addWidget(self.users, 1)
            act = QHBoxLayout()
            act.addStretch(1)
            act.addWidget(button("Edit", None, lambda: self.edit_user(self.users.selected())))
            act.addWidget(button("Reset password", None, self.reset_password))
            act.addWidget(button("Activate / Deactivate", None, self.toggle_user))
            l.addLayout(act)
            tabs.addTab(w, "Users")
        if ctx.can(Perm.MANAGE_ROLES):
            w2 = QWidget()
            l2 = QVBoxLayout(w2)
            l2.setContentsMargins(0, 8, 0, 0)
            bar2 = QHBoxLayout()
            bar2.addWidget(label("Roles group permissions. Default roles can be edited to match "
                                 "how your business works.", "Muted"), 1)
            bar2.addWidget(button("New role", "primary", lambda: self.edit_role(None)))
            l2.addLayout(bar2)
            self.roles = DataTable([Col("name", "Role"), Col("description", "Description"),
                                    Col("perm_count", "Permissions", "int"),
                                    Col("user_count", "Users", "int")], stretch="description")
            self.roles.activated.connect(self.edit_role)
            l2.addWidget(self.roles, 1)
            act2 = QHBoxLayout()
            act2.addStretch(1)
            act2.addWidget(button("Edit permissions", None,
                                  lambda: self.edit_role(self.roles.selected())))
            act2.addWidget(button("Delete role", "danger", self.delete_role))
            l2.addLayout(act2)
            tabs.addTab(w2, "Roles & permissions")

    def on_show(self):
        self.load()

    @ui_action
    def load(self):
        if self.ctx.can(Perm.MANAGE_USERS):
            rows = self.ctx.services.users.list_users(self.ctx.user)
            for r in rows:
                r["status"] = "Active" if r["is_active"] else "Inactive"
            self.users.set_rows(rows)
        if self.ctx.can(Perm.MANAGE_ROLES):
            roles = self.ctx.services.users.list_roles(self.ctx.user)
            for r in roles:
                r["perm_count"] = len(r["permissions"])
            self.roles.set_rows(roles)

    def _role_options(self):
        return [(r["name"], r["id"]) for r in self.ctx.services.users.list_roles(self.ctx.user)]

    @ui_action
    def new_user(self):
        def submit(d):
            if d["password"] != d["confirm"]:
                raise ValidationError("Passwords do not match.")
            return self.ctx.services.users.create_user(self.ctx.user, d)
        if FormDialog(self, "New user", [
                Field("username", "Username", required=True, max_length=32),
                Field("full_name", "Full name", max_length=128),
                Field("role_id", "Role", "combo", required=True, options=self._role_options()),
                Field("password", "Temporary password", "password", required=True,
                      help=PASSWORD_HELP),
                Field("confirm", "Confirm password", "password", required=True),
                Field("must_change_password", "Require password change at first sign-in",
                      "check")], {"must_change_password": True}, submit, width=520).exec():
            self.ctx.toast("User created")
            self.load()

    @ui_action
    def edit_user(self, row):
        if not row:
            show_info(self, "Select a user first.")
            return
        if FormDialog(self, f"Edit user — {row['username']}", [
                Field("full_name", "Full name", max_length=128),
                Field("role_id", "Role", "combo", required=True, options=self._role_options())],
                row, lambda d: self.ctx.services.users.update_user(self.ctx.user, row["id"], d)
                ).exec():
            self.load()

    @ui_action
    def reset_password(self):
        r = self.users.selected()
        if not r:
            show_info(self, "Select a user first.")
            return

        def submit(d):
            if d["password"] != d["confirm"]:
                raise ValidationError("Passwords do not match.")
            self.ctx.services.users.reset_password(self.ctx.user, r["id"], d["password"])
        if FormDialog(self, f"Reset password — {r['username']}", [
                Field("password", "New password", "password", required=True, help=PASSWORD_HELP),
                Field("confirm", "Confirm password", "password", required=True)],
                on_submit=submit, intro="The user will be asked to choose a new password at "
                                        "next sign-in.").exec():
            self.ctx.toast("Password reset")

    @ui_action
    def toggle_user(self):
        r = self.users.selected()
        if not r:
            show_info(self, "Select a user first.")
            return
        new = not r["is_active"]
        if confirm(self, f"{'Activate' if new else 'Deactivate'} {r['username']}?"):
            self.ctx.services.users.update_user(self.ctx.user, r["id"], {"is_active": new})
            self.load()

    @ui_action
    def edit_role(self, row):
        perms = self.ctx.services.users.list_permissions(self.ctx.user)
        if RoleDialog(self, self.ctx, row, perms).exec():
            self.ctx.toast("Role saved")
            self.load()

    @ui_action
    def delete_role(self):
        r = self.roles.selected()
        if not r:
            show_info(self, "Select a role first.")
            return
        if confirm(self, f"Delete role “{r['name']}”?", danger=True, yes_text="Delete"):
            self.ctx.services.users.delete_role(self.ctx.user, r["id"])
            self.load()
