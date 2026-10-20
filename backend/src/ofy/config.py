"""Bootstrap configuration (environment) and runtime settings (persisted, editable from the UI)."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ofy import __version__
from ofy.download.paths import DEFAULT_TEMPLATE, LEGACY_DEFAULT_TEMPLATES

# MusicBrainz asks for "App/version ( contact )"; the contact comes from OFY_CONTACT when set.
USER_AGENT = f"Ofy/{__version__}"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"OFY_{name}", default)


def default_data_dir() -> Path:
    """Per-user app data: $XDG_DATA_HOME/ofy (~/.local/share/ofy), %APPDATA%\\Ofy on Windows."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Ofy"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Ofy"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "ofy"


# The app used to be called "Offliner"; its data directory is moved over once (see migrate_legacy_data_dir).
LEGACY_NAME = "offliner"


def _legacy_data_dir() -> Path:
    d = default_data_dir()
    return d.with_name(LEGACY_NAME.capitalize() if d.name == "Ofy" else LEGACY_NAME)


def migrate_legacy_data_dir() -> Path | None:
    """Move the pre-rename data directory (DB, caches, settings) to the new default location.

    Only runs for the default location, when the new directory doesn't exist yet and no old
    instance is running. Returns the new directory if something was migrated.
    """
    if os.environ.get("OFY_DATA_DIR"):
        return None
    new, old = default_data_dir(), _legacy_data_dir()
    if new.exists() or not old.is_dir() or (old / "desktop-instance.json").exists():
        return None
    old.rename(new)
    for f in new.glob(f"{LEGACY_NAME}.db*"):
        f.rename(new / f.name.replace(f"{LEGACY_NAME}.db", "ofy.db", 1))
    # The desktop webview's HTTP cache may hold the old UI (served before index.html was sent with
    # Cache-Control: no-cache); drop it so the renamed UI loads. Local storage is kept.
    shutil.rmtree(new / "webview" / "cache", ignore_errors=True)
    return new


def default_library_dir() -> Path:
    return Path.home() / "Music" / "Ofy"


def default_static_dir() -> Path:
    """The built frontend: <repo>/frontend/dist next to backend/src/ofy."""
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


@dataclass(frozen=True)
class Env:
    """Process-level configuration read once from environment variables."""

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(default_data_dir()))).expanduser().resolve())
    default_library: Path = field(default_factory=lambda: Path(_env("LIBRARY_DIR", str(default_library_dir()))).expanduser().resolve())
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8080")))
    static_dir: Path = field(default_factory=lambda: Path(_env("STATIC_DIR", str(default_static_dir()))).expanduser().resolve())
    musicbrainz_url: str = field(default_factory=lambda: _env("MUSICBRAINZ_URL", "https://musicbrainz.org/ws/2"))
    coverart_url: str = field(default_factory=lambda: _env("COVERART_URL", "https://coverartarchive.org"))
    contact: str = field(default_factory=lambda: _env("CONTACT", ""))
    scan_on_startup: bool = field(default_factory=lambda: _env("SCAN_ON_STARTUP", "1") == "1")
    start_workers: bool = field(default_factory=lambda: _env("START_WORKERS", "1") == "1")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ofy.db"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def cover_cache_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def user_agent(self) -> str:
        if self.contact:
            return f"Ofy/{__version__} ( {self.contact} )"
        return USER_AGENT


env = Env()


# Stands in for a saved password in API responses; sending it back keeps the saved password.
PASSWORD_MASK = "••••••••"


class Settings(BaseModel):
    """User-editable settings; stored as JSON in the database."""

    library_path: str = Field(default_factory=lambda: str(env.default_library))
    output_format: Literal["mp3", "m4a", "opus"] = "mp3"
    mp3_quality: Literal["320", "v0"] = "320"
    path_template: str = DEFAULT_TEMPLATE
    concurrency: int = Field(default=2, ge=1, le=8)
    match_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    lyrics_fetch: bool = True
    lyrics_prefer_synced: bool = True
    lyrics_embed: bool = True
    lrclib_url: str = "https://lrclib.net"
    cookies_path: str = ""
    max_retries: int = Field(default=3, ge=0, le=10)
    # Sync to a remote peer (rsync over SSH; no host = a local folder, e.g. a mounted drive)
    sync_host: str = ""
    sync_user: str = ""
    sync_port: int = Field(default=22, ge=1, le=65535)
    sync_path: str = ""
    sync_ssh_key: str = ""
    sync_password: str = ""  # stored in plain text; the API only ever returns PASSWORD_MASK for it
    sync_delete: bool = True

    @field_validator("path_template")
    @classmethod
    def _upgrade_old_default(cls, v: str) -> str:
        # Users who never customized the template follow the current default.
        return DEFAULT_TEMPLATE if v in LEGACY_DEFAULT_TEMPLATES else v
