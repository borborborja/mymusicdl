"""Resolve only recorded audio inside the configured shared music volume."""

from pathlib import Path

AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".alac": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".aiff": "audio/aiff",
}


def library_file(root: Path, path: str | None) -> Path:
    if not path:
        raise ValueError("Esta descarga no tiene un archivo guardado.")
    try:
        candidate = Path(path).resolve(strict=True)
        if not candidate.is_relative_to(root.resolve()):
            raise ValueError("El archivo está fuera de la biblioteca compartida.")
        if candidate.suffix.lower() not in AUDIO_TYPES:
            raise ValueError("El archivo no tiene un formato de audio permitido.")
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise ValueError("El archivo de audio está vacío o no es un archivo regular.")
        return candidate
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            "No se puede leer el archivo. Comprueba el volumen de música y sus permisos."
        ) from exc
