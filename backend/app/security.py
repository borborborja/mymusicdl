"""Symmetric encryption for provider credentials stored in the DB.

A Fernet key is derived from ``APP_SECRET`` so tokens (Tidal/Qobuz/Deezer) are never stored in
plaintext. Rotating APP_SECRET invalidates stored credentials (they'd need re-entering)."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken


def is_youtube_url(url: str) -> bool:
    """Accept only HTTP(S) URLs on YouTube's actual domains."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme in {"http", "https"}
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 80, 443}
            and any(
                host == domain or host.endswith("." + domain)
                for domain in ("youtube.com", "youtu.be")
            )
        )
    except ValueError:
        return False


def youtube_track_url(url: str) -> str | None:
    """Normalize one video URL and discard playlist/channel URLs and playlist parameters."""
    if not is_youtube_url(url):
        return None
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname.rstrip(".").lower() == "youtu.be" and len(parts) == 1:
        video_id = parts[0]
    elif parts[0] == "watch":
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
        video_id = parts[1]
    else:
        return None
    if not video_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in video_id
    ):
        return None
    return "https://www.youtube.com/watch?" + urlencode({"v": video_id})


def _key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256((secret or "").encode()).digest())


def encrypt_secret(plaintext: str, secret: str) -> str:
    return Fernet(_key(secret)).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, secret: str) -> str:
    try:
        return Fernet(_key(secret)).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt credential (APP_SECRET changed?)") from exc
