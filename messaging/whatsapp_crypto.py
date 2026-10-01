"""AES-GCM encryption for WhatsApp Business access tokens."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from rest_framework.exceptions import ValidationError

_PREFIX = "v1:"
_NONCE_LEN = 12


class WhatsAppCryptoError(Exception):
    """Safe failure when token encryption or decryption cannot proceed."""


def _load_key() -> bytes:
    raw = (getattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", "") or "").strip()
    if not raw:
        raise WhatsAppCryptoError("WHATSAPP_TOKEN_ENCRYPTION_KEY is not configured.")
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
        if len(key) == 32:
            return key
    except Exception:
        pass
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_token(value: str | None) -> str:
    if value is None or value == "":
        return ""
    aesgcm = AESGCM(_load_key())
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
    packed = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{_PREFIX}{packed}"


def decrypt_token(value: str | None) -> str:
    if value is None or value == "":
        return ""
    if not str(value).startswith(_PREFIX):
        raise WhatsAppCryptoError("Unrecognized encrypted token format.")
    packed = str(value)[len(_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(packed.encode("ascii"))
    except Exception as exc:
        raise WhatsAppCryptoError("Invalid encrypted token encoding.") from exc
    if len(raw) <= _NONCE_LEN:
        raise WhatsAppCryptoError("Invalid encrypted token payload.")
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        plaintext = AESGCM(_load_key()).decrypt(nonce, ciphertext, None)
    except WhatsAppCryptoError:
        raise
    except Exception as exc:
        raise WhatsAppCryptoError("Unable to decrypt token.") from exc
    return plaintext.decode("utf-8")


def require_encryption_configured() -> None:
    try:
        _load_key()
    except WhatsAppCryptoError as exc:
        raise ValidationError(
            {"detail": "WhatsApp token encryption is not configured.", "error_code": "CONFIG_ERROR"}
        ) from exc
