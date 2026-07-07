"""Bot adapter contract + status DTO shared by every messaging backend."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class BotStatus:
    name: str
    enabled: bool = False  # configured → we attempt to run it
    configured: bool = False
    source: str | None = None  # where the config came from: "env" | "db" | None
    running: bool = False  # background loop is alive
    connected: bool = False  # last poll/sync succeeded
    identity: str | None = None  # bot username (Telegram) / user id (Matrix)
    allowed_count: int = 0  # size of the allowlist
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "configured": self.configured,
            "source": self.source,
            "running": self.running,
            "connected": self.connected,
            "identity": self.identity,
            "allowed_count": self.allowed_count,
            "error": self.error,
        }


class BotAdapter(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True when enough credentials are present to attempt a connection."""

    @property
    def enabled(self) -> bool:
        return self.configured

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def status(self) -> BotStatus: ...

    async def on_job_terminal(self, job: dict) -> None:
        """Notify the originating chat that one of its downloads finished/failed. No-op by default."""
        return None
