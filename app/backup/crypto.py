"""Backup file encryption (AES-256-GCM, key from the password via scrypt).

File layout (all integers big-endian):

    magic      8 bytes   b"BPOSENC1"
    salt      16 bytes   scrypt salt
    log2(N)    1 byte    scrypt cost, r = 8, p = 1
    nonce     12 bytes   AES-GCM nonce
    data       rest      AES-GCM ciphertext + 16-byte tag

The header is authenticated as associated data, so any change to the file
(or a wrong password) makes decryption fail instead of returning bad data.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.services.errors import BusinessError

MAGIC = b"BPOSENC1"
_SALT, _NONCE, _HEADER = 16, 12, 8 + 16 + 1 + 12
LOG2_N = 15                     # scrypt N = 32768: ~0.1 s and 32 MB per derivation
MIN_PASSWORD = 8


class PasswordRequired(BusinessError):
    """The backup is encrypted and needs its password."""

    def __init__(self, message: str = "This backup is protected with a backup password."):
        super().__init__(message)


class WrongPassword(BusinessError):
    def __init__(self, message: str = "The backup password is wrong, or the file is damaged."):
        super().__init__(message)


def derive_key(password: str, salt: bytes, log2_n: int = LOG2_N) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** log2_n, r=8, p=1).derive(password.encode("utf-8"))


def new_key(password: str) -> tuple[bytes, bytes]:
    """(salt, key) for a newly chosen password."""
    salt = os.urandom(_SALT)
    return salt, derive_key(password, salt)


def is_encrypted(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def encrypt(plain: bytes, key: bytes, salt: bytes, log2_n: int = LOG2_N) -> bytes:
    header = MAGIC + salt + bytes([log2_n]) + os.urandom(_NONCE)
    return header + AESGCM(key).encrypt(header[-_NONCE:], plain, header)


def decrypt(blob: bytes, *, password: str | None = None, key: bytes | None = None) -> bytes:
    """Decrypt with the password (any PC) or with the stored key (this PC)."""
    if len(blob) < _HEADER + 16 or not blob.startswith(MAGIC):
        raise WrongPassword("This is not an encrypted BusinessPOS backup.")
    header = blob[:_HEADER]
    salt, log2_n, nonce = header[8:24], header[24], header[25:]
    if key is None:
        if not password:
            raise PasswordRequired()
        if not 10 <= log2_n <= 20:
            raise WrongPassword()
        key = derive_key(password, salt, log2_n)
    try:
        return AESGCM(key).decrypt(nonce, blob[_HEADER:], header)
    except InvalidTag:
        raise WrongPassword() from None


def salt_of(blob_or_path) -> bytes:
    data = Path(blob_or_path).read_bytes()[:_HEADER] if isinstance(blob_or_path, (str, Path)) \
        else blob_or_path[:_HEADER]
    return data[8:24]
