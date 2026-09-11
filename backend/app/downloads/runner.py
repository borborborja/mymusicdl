"""Subprocess streaming helper.

Runs a CLI tool, reads stdout line-by-line, and turns each line into a ``ProgressEvent`` via a
provider-supplied ``parse`` callback. On cancellation (the worker cancels the consuming task) the
child process *group* is terminated so no orphaned ffmpeg/yt-dlp lingers.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections import deque
from collections.abc import AsyncIterator, Callable

from backend.app.config import Settings
from backend.app.logging import get_logger
from backend.app.providers.base import ProgressEvent

log = get_logger(__name__)

ParseFn = Callable[[str], ProgressEvent | None]


async def terminate_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate and reap a subprocess started in its own process group."""
    if proc.returncode is not None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            pass
        # Descendants can outlive the group leader or ignore SIGTERM.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass
    finally:
        await proc.wait()


class SubprocessError(RuntimeError):
    def __init__(self, returncode: int, output: str) -> None:
        self.returncode = returncode
        self.output = output
        super().__init__(f"command failed (exit {returncode})\n{output}")


def tool_env(settings: Settings) -> dict[str, str]:
    """Environment for tool subprocesses: tools-venv bin first on PATH, then the system PATH
    (so spotdl/yt-dlp find the venv tools and the system ffmpeg)."""
    env = dict(os.environ)
    venv_bin = str(settings.tools_venv_path / "bin")
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


async def stream_subprocess(
    cmd: list[str],
    *,
    job_id: str,
    parse: ParseFn,
    settings: Settings,
    cwd: str | None = None,
) -> AsyncIterator[ProgressEvent]:
    """Yield ProgressEvents parsed from the command's combined stdout/stderr.

    Raises SubprocessError on a non-zero exit (with the tail of the output for diagnostics).
    """
    # Arguments can contain Spotify secrets, tokens, or signed URLs.
    log.info("[job %s] exec: %s", job_id, os.path.basename(cmd[0]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=tool_env(settings),
        start_new_session=True,  # own process group → clean kill on cancel
    )
    tail: deque[str] = deque(maxlen=40)
    idle_timeout = settings.download_idle_timeout_s or None
    try:
        assert proc.stdout is not None
        while True:
            try:
                raw = (
                    await asyncio.wait_for(proc.stdout.readline(), timeout=idle_timeout)
                    if idle_timeout
                    else await proc.stdout.readline()
                )
            except asyncio.TimeoutError:
                # No output for the whole window — assume the tool hung. Raising here trips the
                # finally block, which kills the process group and frees the worker slot.
                raise SubprocessError(
                    -1,
                    f"Sin salida durante {idle_timeout}s — descarga colgada, abortada.\n"
                    + "\n".join(tail),
                ) from None
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            event = parse(line)
            if event is not None:
                yield event
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=idle_timeout)
        except TimeoutError:
            raise SubprocessError(-1, "Sin salida — descarga colgada tras cerrar stdout") from None
        if rc != 0:
            raise SubprocessError(rc, "\n".join(tail))
    finally:
        await terminate_process(proc)
