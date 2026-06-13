"""Dependency-injection helpers.

App-wide singletons (provider registry, Navidrome client, progress broker, download queue,
search aggregator, updater) are built once in the lifespan and stashed on ``app.state``; these
accessors read them back for routers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.app.config import Settings, get_settings

if TYPE_CHECKING:  # avoid import cycles at runtime
    from backend.app.downloads.progress import ProgressBroker
    from backend.app.downloads.queue import DownloadQueue
    from backend.app.metadata.aggregator import SearchAggregator
    from backend.app.navidrome.client import NavidromeClient
    from backend.app.providers.registry import ProviderRegistry
    from backend.app.updater.service import Updater


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def get_registry(request: Request) -> "ProviderRegistry":
    return request.app.state.registry


def get_broker(request: Request) -> "ProgressBroker":
    return request.app.state.broker


def get_queue(request: Request) -> "DownloadQueue":
    return request.app.state.queue


def get_navidrome(request: Request) -> "NavidromeClient | None":
    return request.app.state.navidrome


def get_aggregator(request: Request) -> "SearchAggregator":
    return request.app.state.aggregator


def get_updater(request: Request) -> "Updater":
    return request.app.state.updater


def require_auth(
    settings: SettingsDep,
    x_app_password: Annotated[str | None, Header()] = None,
) -> None:
    """Optional shared-secret gate layered on top of Cloudflare Access.

    If ``APP_SHARED_PASSWORD`` is empty, this is a no-op (the edge already authenticated the user).
    """
    expected = settings.app_shared_password
    if not expected:
        return
    if x_app_password != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-App-Password",
        )


AuthDep = Annotated[None, Depends(require_auth)]
