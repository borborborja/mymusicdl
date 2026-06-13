"""Provider registry — builds the providers and exposes only the enabled ones.

Paid providers are constructed with whatever credentials exist at boot (env vars); the Settings
route can later call ``set_credentials`` to flip one on without a restart.
"""
from __future__ import annotations

from backend.app.config import Settings
from backend.app.providers.base import Provider
from backend.app.providers.spotdl_provider import SpotdlProvider
from backend.app.providers.streamrip_provider import (
    DeezerProvider,
    QobuzProvider,
    TidalProvider,
)
from backend.app.providers.ytdlp_provider import YtdlpProvider


class ProviderRegistry:
    def __init__(self, providers: list[Provider]) -> None:
        self._providers: dict[str, Provider] = {p.id: p for p in providers}

    def all(self) -> list[Provider]:
        return list(self._providers.values())

    def enabled(self) -> list[Provider]:
        return [p for p in self._providers.values() if p.enabled]

    def get(self, provider_id: str) -> Provider | None:
        return self._providers.get(provider_id)

    def set_credentials(self, provider_id: str, creds: dict | None) -> bool:
        p = self._providers.get(provider_id)
        if p is None:
            return False
        p.set_credentials(creds)
        return True

    def infos(self) -> list[dict]:
        return [p.info() for p in self._providers.values()]


def _creds_from_settings(settings: Settings) -> dict[str, dict | None]:
    return {
        "tidal": {"token": settings.tidal_token} if settings.tidal_token else None,
        "qobuz": {"token": settings.qobuz_token} if settings.qobuz_token else None,
        "deezer": {"arl": settings.deezer_arl} if settings.deezer_arl else None,
    }


def build_registry(settings: Settings) -> ProviderRegistry:
    creds = _creds_from_settings(settings)
    providers: list[Provider] = [
        # ── free, always enabled ──
        SpotdlProvider(settings),
        YtdlpProvider(settings),
        # ── paid, disabled until credentials are present ──
        TidalProvider(settings, creds["tidal"]),
        QobuzProvider(settings, creds["qobuz"]),
        DeezerProvider(settings, creds["deezer"]),
        # To prefer the tiddl backend for Tidal instead of streamrip, register it here:
        #   TiddlProvider(settings, creds["tidal"]),
    ]
    return ProviderRegistry(providers)
