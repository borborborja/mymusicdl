"""Download destination layout.

A configurable template decides the folder structure *inside* the Navidrome music volume — e.g.
``{artist}/{album}/{title}`` → ``<music>/Artista/Álbum/Canción.<ext>``. The base root is always
``MUSIC_LIBRARY_PATH`` (golden rule #2: writes must land on the volume Navidrome mounts), so the
template only controls the structure under it and is validated to never escape that root.
"""
from __future__ import annotations

import os
import re

DEFAULT_LAYOUT = "{artist}/{album}/{title}"
ALLOWED_TOKENS = {"artist", "album", "title", "year"}

_TOKEN_RE = re.compile(r"\{(\w+)\}")
# Characters that are illegal/awkward in path components across filesystems, plus the brace/percent
# tokens that would otherwise be interpreted by the spotdl / yt-dlp output templates.
_ILLEGAL = re.compile(r'[<>:"/\\|?*{}%\x00-\x1f]')

_FALLBACKS = {
    "artist": "Unknown Artist",
    "album": "Unknown Album",
    "title": "Unknown Title",
    "year": "Unknown Year",
}


def validate_layout(template: str) -> None:
    """Raise ``ValueError`` if the template is unusable or could escape the music root."""
    if not template or not template.strip():
        raise ValueError("La plantilla no puede estar vacía")
    if os.path.isabs(template) or template.startswith(("/", "\\", "~")):
        raise ValueError("La plantilla debe ser relativa (no rutas absolutas)")
    if ".." in template.split("/"):
        raise ValueError("La plantilla no puede contener '..'")
    unknown = set(_TOKEN_RE.findall(template)) - ALLOWED_TOKENS
    if unknown:
        raise ValueError(
            f"Tokens desconocidos: {', '.join(sorted(unknown))}. "
            f"Permitidos: {', '.join(sorted(ALLOWED_TOKENS))}"
        )
    if "{title}" not in template:
        raise ValueError("La plantilla debe incluir {title} para el nombre del archivo")


def _sanitize(component: str, fallback: str) -> str:
    """Make one path component filesystem-safe; fall back when it ends up empty."""
    cleaned = _ILLEGAL.sub(" ", component or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def render_example(template: str) -> str:
    """A human-readable preview for the Settings UI."""
    dest_rel, filename = _render(
        template, artist="Daft Punk", album="Discovery", title="One More Time", year="2001"
    )
    return os.path.join(dest_rel, filename) if dest_rel else filename


def _render(
    template: str, *, artist: str, album: str, title: str, year: str
) -> tuple[str, str]:
    values = {"artist": artist, "album": album, "title": title, "year": year}

    def repl(m: re.Match) -> str:
        tok = m.group(1)
        return values.get(tok, "") if tok in ALLOWED_TOKENS else m.group(0)

    rendered = _TOKEN_RE.sub(repl, template)
    segments = [s for s in rendered.split("/")]
    # Sanitize every segment; the last one is the filename base, the rest are directories.
    *dir_segs, file_seg = segments
    safe_dirs = [_sanitize(s, "Unknown") for s in dir_segs if s.strip()]
    filename = _sanitize(file_seg, "track")
    return os.path.join(*safe_dirs) if safe_dirs else "", filename


def build_dest(
    base: str,
    template: str,
    *,
    artist: str | None,
    album: str | None,
    title: str | None,
    year: int | str | None = None,
) -> tuple[str, str]:
    """Return ``(dest_dir, filename)`` under ``base`` for this track.

    ``dest_dir`` is created by the caller. Guarantees the result stays within ``base`` (golden rule
    #2); falls back to the default layout if a bad template slips through.
    """
    try:
        validate_layout(template)
    except ValueError:
        template = DEFAULT_LAYOUT

    dir_rel, filename = _render(
        template,
        artist=_sanitize(artist or "", _FALLBACKS["artist"]),
        album=_sanitize(album or "", _FALLBACKS["album"]),
        title=_sanitize(title or "", _FALLBACKS["title"]),
        year=str(year) if year else "",
    )

    base_abs = os.path.abspath(base)
    dest_dir = os.path.abspath(os.path.join(base_abs, dir_rel)) if dir_rel else base_abs
    # Containment guard: if the join somehow escaped the music root, fall back to the root itself.
    if os.path.commonpath([base_abs, dest_dir]) != base_abs:
        dest_dir = base_abs
    return dest_dir, filename
