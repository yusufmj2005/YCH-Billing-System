"""Protect stored credentials (e.g. the Razorpay key secret) with Windows DPAPI.

On Windows the secret is encrypted for the signed-in Windows user, so a copied
database or backup is useless on another computer or account: the secret must
simply be entered again there. Other platforms (development and tests only)
store it unprotected, clearly marked.
"""
from __future__ import annotations

import base64
import os

from app.services.errors import BusinessError

_DPAPI = "dpapi:"
_PLAIN = "plain:"


class SecretUnavailable(BusinessError):
    def __init__(self, message: str = "The saved secret cannot be read on this computer or "
                                      "Windows account. Enter it again."):
        super().__init__(message)


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data, len(data))
    src = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not fn(ctypes.byref(src), "BusinessPOS" if protect else None, None, None, None,
              CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(secret: str) -> str:
    data = secret.encode("utf-8")
    if os.name == "nt":
        return _DPAPI + base64.b64encode(_dpapi(data, True)).decode("ascii")
    return _PLAIN + base64.b64encode(data).decode("ascii")


def unprotect(stored: str) -> str:
    try:
        if stored.startswith(_DPAPI):
            if os.name != "nt":
                raise SecretUnavailable()
            return _dpapi(base64.b64decode(stored[len(_DPAPI):]), False).decode("utf-8")
        if stored.startswith(_PLAIN):
            return base64.b64decode(stored[len(_PLAIN):]).decode("utf-8")
    except SecretUnavailable:
        raise
    except Exception:  # noqa: BLE001 - another PC/user, or damaged value
        raise SecretUnavailable() from None
    raise SecretUnavailable()
