"""Application settings, env-driven via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── networking ──
    port: int = 8080

    # ── paths (container defaults; overridden by env in compose) ──
    app_data_dir: str = "./data"
    music_library_path: str = "./music"
    tools_venv: str = "./data/toolsvenv"

    # ── Navidrome / Subsonic ──
    navidrome_url: str | None = None
    navidrome_user: str | None = None
    navidrome_password: str | None = None

    # ── Spotify metadata (client-credentials) ──
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None

    # ── downloads ──
    download_concurrency: int = 2
    default_format: str = "mp3"
    default_bitrate: str = "320k"

    # ── updater ──
    version_check_interval_hours: int = 24
    github_token: str | None = None

    # ── security ──
    app_secret: str = "dev-insecure-secret-change-me"
    app_shared_password: str | None = None

    # ── messaging bots (same functionality as the web, over chat) ──
    # Defining a token/credentials here enables the bot; leave blank to configure it in Settings.
    telegram_bot_token: str | None = None
    telegram_allowed_users: str | None = None  # CSV of numeric Telegram user IDs (allowlist)
    matrix_homeserver: str | None = None  # e.g. https://matrix.org
    matrix_user_id: str | None = None  # e.g. @musicbot:matrix.org
    matrix_access_token: str | None = None
    matrix_allowed_users: str | None = None  # CSV of @user:server allowed to command the bot
    matrix_room_id: str | None = None  # optional: only respond in this room

    # ── paid providers (presence enables the corresponding adapter) ──
    tidal_token: str | None = None
    qobuz_token: str | None = None
    deezer_arl: str | None = None

    # ── derived ──
    @property
    def data_path(self) -> Path:
        return Path(self.app_data_dir)

    @property
    def database_path(self) -> Path:
        return self.data_path / "mymusicdl.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def music_path(self) -> Path:
        return Path(self.music_library_path)

    @property
    def tools_venv_path(self) -> Path:
        return Path(self.tools_venv)

    def tool_bin(self, name: str) -> str:
        """Absolute path to an executable inside the mounted tools venv."""
        return str(self.tools_venv_path / "bin" / name)

    def ensure_dirs(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.music_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
