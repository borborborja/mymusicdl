"""Write the selected catalog identity without re-encoding the downloaded audio."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
from pathlib import Path

from backend.app.downloads.runner import terminate_process
from backend.app.providers.base import TrackRef
from backend.app.schemas.collection import mbid


async def tag_audio(path: str, track: TrackRef) -> None:
    source = Path(path)
    mode = stat.S_IMODE(source.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=".mymusicdl-tags-", suffix=source.suffix, dir=source.parent)
    os.close(fd)
    temporary = Path(name)
    proc = None
    try:
        tags = {"title": track.title, "artist": track.artist}
        if track.album:
            tags["album"] = track.album
        if track.album_artist:
            tags["album_artist"] = track.album_artist
        elif track.provider_id == "ytdlp":
            tags["album_artist"] = track.artist
        if track.isrc:
            tags["ISRC"] = track.isrc
        recording_id = mbid(track.ext_ids.get("mbid"))
        if recording_id:
            tags["MUSICBRAINZ_TRACKID"] = recording_id
        artist_id = mbid(track.ext_ids.get("artist_mbid"))
        if artist_id:
            tags["MUSICBRAINZ_ARTISTID"] = artist_id
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map",
            "0:v?",
            "-map_metadata",
            "0",
            "-c",
            "copy",
        ]
        for key, value in tags.items():
            cmd.extend(["-metadata", f"{key}={value}"])
            cmd.extend(["-metadata:s:a:0", f"{key}={value}"])
        cmd.append(str(temporary))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        _, error = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or temporary.stat().st_size == 0:
            raise RuntimeError(
                "No se pudieron guardar las etiquetas del audio: "
                + error.decode("utf-8", "replace")[-1000:]
            )
        # mkstemp defaults to 0600; preserve access for the separate Navidrome container.
        os.chmod(temporary, mode)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, source)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No se encuentra ffmpeg o el archivo descargado; no se puede preparar para Navidrome."
        ) from exc
    finally:
        if proc is not None:
            await terminate_process(proc)
        temporary.unlink(missing_ok=True)
