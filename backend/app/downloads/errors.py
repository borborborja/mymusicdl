"""Turn raw downloader stderr into a short, actionable message for the UI.

The CLIs (spotdl / yt-dlp / streamrip) emit verbose tracebacks; surfacing the raw text in the queue
is noise. We map a few well-known failure signatures to a friendly hint and keep the rest as-is.
"""
from __future__ import annotations

# (substring to look for [lowercased], friendly message)
_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (
        ("deno", "javascript runtime", "could not find a javascript", "nsig", "jsinterp"),
        "Falta un runtime de JavaScript (Deno) para YouTube. Actualiza la imagen o instala Deno.",
    ),
    (
        ("sign in to confirm", "not a bot", "http error 429", "too many requests"),
        "YouTube está limitando las descargas (rate limit / verificación). Inténtalo más tarde.",
    ),
    (
        ("no results", "no songs found", "lookuperror", "unable to find", "no matches found"),
        "No se encontró la pista en la fuente.",
    ),
    (
        ("temporary failure in name resolution", "connection", "timed out", "timeout", "getaddrinfo"),
        "Error de red al contactar con la fuente. Revisa la conexión.",
    ),
    (
        ("ffmpeg", "ffprobe"),
        "Falta o falla ffmpeg (necesario para extraer/convertir el audio).",
    ),
    (
        ("403", "forbidden", "401", "unauthorized", "invalid credentials", "login"),
        "La fuente rechazó la petición (credenciales o acceso). Revisa los ajustes de la fuente.",
    ),
    (
        ("permission denied", "read-only file system", "no space left"),
        "No se pudo escribir el archivo (permisos o disco lleno) en la carpeta de música.",
    ),
]


def humanize_error(raw: str | None) -> str:
    """Return a friendly hint when the error matches a known pattern, else the original text."""
    text = (raw or "").strip()
    if not text:
        return "La descarga falló sin mensaje."
    low = text.lower()
    for needles, message in _PATTERNS:
        if any(n in low for n in needles):
            return message
    return text
