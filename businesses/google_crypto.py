"""Authenticated encryption for Google OAuth tokens (AES-GCM)."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from rest_framework.exceptions import ValidationError

_PREFIX = "v1:"
_NONCE_LEN = 12


class GoogleCryptoError(Exception):
    """Raised when token encryption/decryption fails safely."""


def _load_key() -> bytes:
    raw = (getattr(settings, "GOOGLE_TOKEN_ENCRYPTION_KEY", "") or "").strip()
    if not raw:
        raise GoogleCryptoError("GOOGLE_TOKEN_ENCRYPTION_KEY is not configured.")
    # Accept urlsafe/base64 32-byte key, or derive from a passphrase for local/dev.
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
        if len(key) == 32:
            return key
    except Exception:
        pass
    # Deterministic 32-byte derivation for non-base64 configured secrets (dev only).
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_token(value: str | None) -> str:
    """Encrypt a secret string. Empty/None → empty string (nothing stored)."""
    if value is None or value == "":
        return ""
    key = _load_key()
    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    packed = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{_PREFIX}{packed}"


def decrypt_token(value: str | None) -> str:
    """Decrypt a previously encrypted token. Empty → empty."""
    if value is None or value == "":
        return ""
    if not value.startswith(_PREFIX):
        raise GoogleCryptoError("Unrecognized encrypted token format.")
    packed = value[len(_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(packed.encode("ascii"))
    except Exception as exc:
        raise GoogleCryptoError("Invalid encrypted token encoding.") from exc
    if len(raw) <= _NONCE_LEN:
        raise GoogleCryptoError("Invalid encrypted token payload.")
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        key = _load_key()
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except GoogleCryptoError:
        raise
    except Exception as exc:
        raise GoogleCryptoError("Unable to decrypt token.") from exc
    return plaintext.decode("utf-8")


def require_encryption_configured() -> None:
    try:
        _load_key()
    except GoogleCryptoError as exc:
        raise ValidationError({"detail": "Google token encryption is not configured."}) from exc
