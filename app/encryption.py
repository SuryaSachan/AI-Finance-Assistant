"""AES-256-SIV encryption for sensitive financial fields.

Deterministic authenticated encryption: same plaintext always produces the same
ciphertext, so encrypted columns can still be used in WHERE / GROUP BY without
decrypting every row first.  Tampering is detected automatically.

The 512-bit key (256 enc + 256 MAC) lives in the ENCRYPTION_KEY env var.
If it is absent, encryption is disabled and fields pass through in plaintext.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESSIV

from . import config

_cipher: AESSIV | None = None
_enabled: bool | None = None


def _init() -> None:
    global _cipher, _enabled
    key_b64 = config.ENCRYPTION_KEY
    if not key_b64:
        _enabled = False
        return
    _cipher = AESSIV(base64.urlsafe_b64decode(key_b64))
    _enabled = True


def enabled() -> bool:
    if _enabled is None:
        _init()
    return bool(_enabled)


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a single string value.  Returns None for None/empty input."""
    if not plaintext:
        return plaintext
    if _enabled is None:
        _init()
    if not _enabled or _cipher is None:
        return plaintext
    ct = _cipher.encrypt(plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(ct).decode("ascii")


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a single string value.  Returns None for None/empty input."""
    if not ciphertext:
        return ciphertext
    if _enabled is None:
        _init()
    if not _enabled or _cipher is None:
        return ciphertext
    try:
        ct = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        return _cipher.decrypt(ct, None).decode("utf-8")
    except Exception:
        # If decryption fails (e.g. plaintext data from before encryption was enabled),
        # return the value as-is so the app degrades gracefully.
        return ciphertext


def generate_key() -> str:
    """Generate a new AES-256-SIV key (512 bits) and return it base64-encoded."""
    key = AESSIV.generate_key(bit_length=256)
    return base64.urlsafe_b64encode(key).decode("ascii")


# vectorised helpers for pandas columns
def encrypt_series(series):
    """Encrypt every non-null value in a pandas Series."""
    return series.map(lambda v: encrypt(str(v)) if v is not None and str(v).strip() else v)


def decrypt_series(series):
    """Decrypt every non-null value in a pandas Series."""
    return series.map(lambda v: decrypt(str(v)) if v is not None and str(v).strip() else v)
