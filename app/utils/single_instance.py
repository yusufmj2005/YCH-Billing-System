"""Single-instance guard using a named Windows mutex.

The same mutex name is declared as ``AppMutex`` in the Inno Setup script so
the installer/uninstaller can detect a running copy and ask the user to
close it before files are replaced.
"""
from __future__ import annotations

import os

_handle = None


def acquire(name: str) -> bool:
    """Return False if another instance already holds the mutex."""
    global _handle
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _handle = kernel32.CreateMutexW(None, False, name)
    ERROR_ALREADY_EXISTS = 183
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
