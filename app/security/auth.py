"""Authenticated principal + permission enforcement used by every service."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.errors import PermissionDenied


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    role_name: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_admin: bool = False

    def has(self, *perms: str) -> bool:
        return all(p in self.permissions for p in perms)

    def has_any(self, *perms: str) -> bool:
        return any(p in self.permissions for p in perms)

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


def require(actor: CurrentUser | None, *perms: str) -> CurrentUser:
    """Raise PermissionDenied unless ``actor`` holds every permission."""
    if actor is None:
        raise PermissionDenied("Please log in first.")
    missing = [p for p in perms if p not in actor.permissions]
    if missing:
        raise PermissionDenied()
    return actor


def require_any(actor: CurrentUser | None, *perms: str) -> CurrentUser:
    if actor is None:
        raise PermissionDenied("Please log in first.")
    if not any(p in actor.permissions for p in perms):
        raise PermissionDenied()
    return actor
