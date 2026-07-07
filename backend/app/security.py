"""Symmetric encryption for provider credentials stored in the DB.

A Fernet key is derived from ``APP_SECRET`` so tokens (Tidal/Qobuz/Deezer) are never stored in
plaintext. Rotating APP_SECRET invalidates stored credentials (they'd need re-entering)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256((secret or "").encode()).digest())


def encrypt_secret(plaintext: str, secret: str) -> str:
    return Fernet(_key(secret)).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, secret: str) -> str:
    try:
        return Fernet(_key(secret)).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt credential (APP_SECRET changed?)") from exc
