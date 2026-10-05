"""Login, logout, password changes, first-run setup."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select

from app.config.constants import (ADMIN_ROLE_NAME, LOCKOUT_MINUTES, MAX_FAILED_LOGINS,
                                  PaymentKind)
from app.database.database import Database
from app.models import PaymentMethod, Role, Sequence, TaxRate, User
from app.security.auth import CurrentUser
from app.security.passwords import hash_password, validate_password_strength, verify_password
from app.services import audit_service
from app.services.errors import AuthenticationError, ValidationError
from app.services.settings_service import SettingsService
from app.utils.dates import now
from app.validators import common as v

log = logging.getLogger(__name__)

_USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-@")


def validate_username(username: str) -> str:
    u = v.text(username, "Username", required=True, max_len=32)
    if len(u) < 3 or not set(u) <= _USERNAME_CHARS:
        raise ValidationError(
            "Username must be 3-32 characters: letters, digits, '.', '_', '-' or '@'.")
    return u


def to_current_user(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id, username=user.username, full_name=user.full_name or "",
        role_name=user.role.name,
        permissions=frozenset(p.code for p in user.role.permissions),
        is_admin=user.role.is_system,
    )


class AuthService:
    def __init__(self, db: Database, settings: SettingsService):
        self.db = db
        self.settings = settings

    def has_users(self) -> bool:
        with self.db.session() as s:
            return bool(s.scalar(select(func.count(User.id))))

    def login(self, username: str, password: str) -> CurrentUser:
        username = (username or "").strip()
        generic = AuthenticationError("Invalid username or password.")
        if not username or not password:
            raise generic
        with self.db.session() as s:
            user = s.scalar(select(User).where(User.username == username))
            if user is None:
                audit_service.record(s, None, "LOGIN_FAILED", "user", None,
                                     {"username": username[:64]}, username=username[:64])
                raise generic
            if user.locked_until and user.locked_until > now():
                raise AuthenticationError(
                    "This account is temporarily locked after repeated failed attempts. "
                    "Please try again in a few minutes.")
            if not verify_password(password, user.password_hash):
                user.failed_attempts += 1
                if user.failed_attempts >= MAX_FAILED_LOGINS:
                    user.locked_until = now() + timedelta(minutes=LOCKOUT_MINUTES)
                    user.failed_attempts = 0
                audit_service.record(s, None, "LOGIN_FAILED", "user", user.id,
                                     username=user.username)
                # commit the counter even though we raise
                s.commit()
                raise generic
            if not user.is_active:
                raise AuthenticationError("This account has been deactivated.")
            user.failed_attempts = 0
            user.locked_until = None
            user.last_login_at = now()
            cu = to_current_user(user)
            audit_service.record(s, cu, "LOGIN", "user", user.id)
            log.info("User %s logged in", user.username)
            return cu

    def logout(self, actor: CurrentUser) -> None:
        with self.db.session() as s:
            audit_service.record(s, actor, "LOGOUT", "user", actor.id)

    def reload(self, actor: CurrentUser) -> CurrentUser:
        """Re-read the user's role/permissions from the database."""
        with self.db.session() as s:
            user = s.get(User, actor.id)
            if user is None or not user.is_active:
                raise AuthenticationError("This account is no longer active.")
            return to_current_user(user)

    def must_change_password(self, actor: CurrentUser) -> bool:
        with self.db.session() as s:
            user = s.get(User, actor.id)
            return bool(user and user.must_change_password)

    def change_password(self, actor: CurrentUser, old_password: str, new_password: str) -> None:
        with self.db.session() as s:
            user = s.get(User, actor.id)
            if user is None or not verify_password(old_password, user.password_hash):
                raise ValidationError("Current password is incorrect.")
            validate_password_strength(new_password, user.username)
            if verify_password(new_password, user.password_hash):
                raise ValidationError("New password must differ from the current password.")
            user.password_hash = hash_password(new_password)
            user.must_change_password = False
            audit_service.record(s, actor, "PASSWORD_CHANGED", "user", user.id)

    # ---- first-run setup -----------------------------------------------------
    def complete_setup(self, data: dict) -> CurrentUser:
        """Create the administrator and save initial business configuration.

        Allowed only once, while no user exists. All in one transaction.
        """
        username = validate_username(data.get("admin_username", ""))
        password = data.get("admin_password", "")
        if password != data.get("admin_password_confirm", ""):
            raise ValidationError("Passwords do not match.")
        validate_password_strength(password, username)
        full_name = v.text(data.get("admin_full_name"), "Full name", max_len=128) or ""

        start_no = int(v.decimal(data.get("invoice_start_number", 1), "Starting invoice number",
                                 min_value=1, max_value=10**9))
        enabled_methods = set(data.get("enabled_payment_methods") or [])
        tax_rates = data.get("tax_rates") or []

        with self.db.session() as s:
            if s.scalar(select(func.count(User.id))):
                raise ValidationError("Setup has already been completed.")
            settings_changes = {
                k: data[k] for k in (
                    "business_name", "business_address", "business_phone", "business_email",
                    "business_gstin", "business_state", "invoice_prefix", "invoice_padding",
                    "invoice_paper", "invoice_footer", "invoice_title", "default_tax_mode",
                    "default_price_includes_tax", "currency_symbol", "logo_path")
                if k in data
            }
            if not v.text(settings_changes.get("business_name"), "Business name"):
                raise ValidationError("Business name is required.")
            self.settings._apply(s, None, settings_changes)
            s.get(Sequence, "invoice").next_value = start_no

            for pm in s.scalars(select(PaymentMethod)):
                if enabled_methods:
                    pm.is_active = pm.kind in enabled_methods
            if not any(pm.is_active for pm in s.scalars(select(PaymentMethod))):
                raise ValidationError("Enable at least one payment method.")

            seen = set()
            for tr in tax_rates:
                name = v.text(tr.get("name"), "Tax name", required=True, max_len=64)
                rate = v.percent(tr.get("rate"), "Tax rate")
                if name.lower() in seen:
                    raise ValidationError(f"Duplicate tax rate name: {name}")
                seen.add(name.lower())
                s.add(TaxRate(name=name, rate=rate))

            role = s.scalar(select(Role).where(Role.name == ADMIN_ROLE_NAME))
            user = User(username=username, full_name=full_name,
                        password_hash=hash_password(password), role=role)
            s.add(user)
            s.flush()
            self.settings._apply(s, None, {"setup_completed": True})
            cu = to_current_user(user)
            audit_service.record(s, cu, "SETUP_COMPLETED", "settings", None,
                                 {"admin": username,
                                  "payment_methods": sorted(enabled_methods or {PaymentKind.CASH})})
            audit_service.record(s, cu, "USER_CREATED", "user", user.id, {"username": username,
                                                                          "role": role.name})
            return cu
