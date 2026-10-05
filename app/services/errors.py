"""Exceptions with messages that are safe to show to end users."""
from __future__ import annotations


class BusinessError(Exception):
    """Base class: ``str(exc)`` is a user-facing message."""


class ValidationError(BusinessError):
    pass


class PermissionDenied(BusinessError):
    def __init__(self, message: str = "You do not have permission to perform this action."):
        super().__init__(message)


class NotFound(BusinessError):
    pass


class InsufficientStock(BusinessError):
    pass


class AuthenticationError(BusinessError):
    pass
