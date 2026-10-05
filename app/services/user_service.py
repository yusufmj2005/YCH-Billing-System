"""Users, roles and permissions administration."""
from __future__ import annotations

from sqlalchemy import func, select

from app.config.constants import Perm
from app.database.database import Database
from app.models import Permission, Role, User
from app.security.auth import CurrentUser, require
from app.security.passwords import hash_password, validate_password_strength
from app.services import audit_service
from app.services.auth_service import validate_username
from app.services.errors import NotFound, ValidationError
from app.validators import common as v


class UserService:
    def __init__(self, db: Database):
        self.db = db

    # ---- users ---------------------------------------------------------------
    def list_users(self, actor: CurrentUser) -> list[dict]:
        require(actor, Perm.MANAGE_USERS)
        with self.db.session() as s:
            return [{
                "id": u.id, "username": u.username, "full_name": u.full_name,
                "role_id": u.role_id, "role": u.role.name, "is_active": u.is_active,
                "last_login_at": u.last_login_at, "must_change_password": u.must_change_password,
            } for u in s.scalars(select(User).order_by(User.username))]

    def _active_admin_count(self, s, exclude_user_id: int | None = None) -> int:
        q = select(func.count(User.id)).join(Role).where(Role.is_system.is_(True),
                                                         User.is_active.is_(True))
        if exclude_user_id:
            q = q.where(User.id != exclude_user_id)
        return s.scalar(q)

    def create_user(self, actor: CurrentUser, data: dict) -> int:
        require(actor, Perm.MANAGE_USERS)
        username = validate_username(data.get("username", ""))
        password = data.get("password", "")
        validate_password_strength(password, username)
        with self.db.session() as s:
            if s.scalar(select(User.id).where(User.username == username)):
                raise ValidationError("That username is already taken.")
            role = s.get(Role, data.get("role_id"))
            if role is None:
                raise ValidationError("Please choose a role.")
            if role.is_system and not actor.is_admin:
                raise ValidationError("Only administrators can create administrator accounts.")
            u = User(username=username,
                     full_name=v.text(data.get("full_name"), "Full name", max_len=128) or "",
                     password_hash=hash_password(password), role=role,
                     must_change_password=bool(data.get("must_change_password", True)))
            s.add(u)
            s.flush()
            audit_service.record(s, actor, "USER_CREATED", "user", u.id,
                                 {"username": username, "role": role.name})
            return u.id

    def update_user(self, actor: CurrentUser, user_id: int, data: dict) -> None:
        require(actor, Perm.MANAGE_USERS)
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                raise NotFound("User not found.")
            changes = {}
            if "full_name" in data:
                u.full_name = v.text(data["full_name"], "Full name", max_len=128) or ""
            if "role_id" in data and data["role_id"] != u.role_id:
                role = s.get(Role, data["role_id"])
                if role is None:
                    raise ValidationError("Please choose a role.")
                if (role.is_system or u.role.is_system) and not actor.is_admin:
                    raise ValidationError("Only administrators can change administrator roles.")
                if u.role.is_system and not role.is_system and \
                        self._active_admin_count(s, exclude_user_id=u.id) == 0:
                    raise ValidationError("At least one active administrator is required.")
                changes["role"] = [u.role.name, role.name]
                u.role = role
            if "is_active" in data and bool(data["is_active"]) != u.is_active:
                if not data["is_active"]:
                    if u.id == actor.id:
                        raise ValidationError("You cannot deactivate your own account.")
                    if u.role.is_system and self._active_admin_count(s, exclude_user_id=u.id) == 0:
                        raise ValidationError("At least one active administrator is required.")
                u.is_active = bool(data["is_active"])
                changes["is_active"] = u.is_active
            audit_service.record(s, actor, "USER_UPDATED", "user", u.id,
                                 {"username": u.username, **changes})

    def reset_password(self, actor: CurrentUser, user_id: int, new_password: str) -> None:
        require(actor, Perm.MANAGE_USERS)
        with self.db.session() as s:
            u = s.get(User, user_id)
            if u is None:
                raise NotFound("User not found.")
            if u.role.is_system and not actor.is_admin:
                raise ValidationError("Only administrators can reset administrator passwords.")
            validate_password_strength(new_password, u.username)
            u.password_hash = hash_password(new_password)
            u.must_change_password = u.id != actor.id
            u.failed_attempts = 0
            u.locked_until = None
            audit_service.record(s, actor, "PASSWORD_RESET", "user", u.id,
                                 {"username": u.username})

    # ---- roles ---------------------------------------------------------------
    def list_permissions(self, actor: CurrentUser) -> list[dict]:
        require(actor, Perm.MANAGE_ROLES)
        with self.db.session() as s:
            return [{"code": p.code, "name": p.name, "group": p.group_name}
                    for p in s.scalars(select(Permission).order_by(Permission.id))]

    def list_roles(self, actor: CurrentUser) -> list[dict]:
        if not actor.has_any(Perm.MANAGE_ROLES, Perm.MANAGE_USERS):
            require(actor, Perm.MANAGE_ROLES)
        with self.db.session() as s:
            counts = dict(s.execute(select(User.role_id, func.count(User.id))
                                    .group_by(User.role_id)).all())
            return [{
                "id": r.id, "name": r.name, "description": r.description or "",
                "is_system": r.is_system, "permissions": sorted(p.code for p in r.permissions),
                "user_count": counts.get(r.id, 0),
            } for r in s.scalars(select(Role).order_by(Role.id))]

    def save_role(self, actor: CurrentUser, role_id: int | None, name: str, description: str,
                  permission_codes: list[str]) -> int:
        require(actor, Perm.MANAGE_ROLES)
        name = v.text(name, "Role name", required=True, max_len=64)
        with self.db.session() as s:
            dup = s.scalar(select(Role.id).where(Role.name == name))
            if dup and dup != role_id:
                raise ValidationError("A role with this name already exists.")
            perms = list(s.scalars(select(Permission).where(Permission.code.in_(permission_codes))))
            if role_id is None:
                role = Role(name=name, description=description or None, permissions=perms)
                s.add(role)
                s.flush()
                action = "ROLE_CREATED"
            else:
                role = s.get(Role, role_id)
                if role is None:
                    raise NotFound("Role not found.")
                if role.is_system:
                    # Administrator always keeps every permission.
                    if name != role.name:
                        raise ValidationError("The Administrator role cannot be renamed.")
                    role.description = description or None
                    audit_service.record(s, actor, "ROLE_UPDATED", "role", role.id,
                                         {"name": role.name})
                    return role.id
                before = sorted(p.code for p in role.permissions)
                role.name = name
                role.description = description or None
                role.permissions = perms
                action = "PERMISSIONS_CHANGED"
                audit_service.record(s, actor, action, "role", role.id, {
                    "name": name,
                    "added": sorted(set(permission_codes) - set(before)),
                    "removed": sorted(set(before) - set(permission_codes)),
                })
                return role.id
            audit_service.record(s, actor, action, "role", role.id,
                                 {"name": name, "permissions": sorted(permission_codes)})
            return role.id

    def delete_role(self, actor: CurrentUser, role_id: int) -> None:
        require(actor, Perm.MANAGE_ROLES)
        with self.db.session() as s:
            role = s.get(Role, role_id)
            if role is None:
                raise NotFound("Role not found.")
            if role.is_system:
                raise ValidationError("The Administrator role cannot be deleted.")
            if s.scalar(select(func.count(User.id)).where(User.role_id == role_id)):
                raise ValidationError("This role is assigned to users and cannot be deleted.")
            name = role.name
            s.delete(role)
            audit_service.record(s, actor, "ROLE_DELETED", "role", role_id, {"name": name})
