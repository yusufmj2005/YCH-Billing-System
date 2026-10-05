"""Password hashing with bcrypt. Plaintext passwords are never stored."""
from __future__ import annotations

import bcrypt

from app.config.constants import MIN_PASSWORD_LENGTH
from app.services.errors import ValidationError

_ROUNDS = 12


def _encode(password: str) -> bytes:
    raw = password.encode("utf-8")
    # bcrypt only uses the first 72 bytes; reject longer to avoid silent truncation.
    if len(raw) > 72:
        raise ValidationError("Password is too long (maximum 72 bytes).")
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("ascii"))
    except (ValueError, ValidationError):
        return False


def validate_password_strength(password: str, username: str = "") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.strip() != password:
        raise ValidationError("Password must not start or end with spaces.")
    if username and password.lower() == username.lower():
        raise ValidationError("Password must not be the same as the username.")
    classes = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                   any(c.isdigit() for c in password), any(not c.isalnum() for c in password)])
    if classes < 2:
        raise ValidationError(
            "Password must mix at least two of: lowercase, uppercase, digits, symbols.")
    _encode(password)
