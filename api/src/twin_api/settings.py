"""Runtime settings, read from the environment (and a local, gitignored .env). No secret defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from twin_api.registry import ArtifactSearch

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWIN_", env_file=".env", extra="ignore")

    # postgresql+psycopg://user:password@host:5432/dbname  (required; never committed)
    database_url: str = Field(..., description="SQLAlchemy URL of the PostgreSQL database")
    repo_root: Path = REPO_ROOT
    # Where serving finds registered model bundles by file name (containers, servers). Optional:
    # without it serving uses the registered path, then repo_root/data/processed/m3/models.
    models_dir: Path | None = None
    environment: str = "development"  # "development" | "test" | "production"
    session_ttl_minutes: int = 8 * 60
    cookie_name: str = "twin_session"
    cookie_secure: bool = True  # set TWIN_COOKIE_SECURE=false only for local http development
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    source_label: str = "CGMacros v1.0.0 (processed by M1/M2)"

    # Google sign-in (optional; ADR-019). All three must be set to enable it. The secret stays on
    # the server. The redirect URI is the app's public callback, which the web app proxies to this
    # API; register exactly this URI with Google, e.g.
    #   http://localhost:3000/api/v1/auth/google/callback
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_redirect_uri: str | None = None
    # Optional: accept only Google Workspace accounts of this domain (the ID token's "hd" claim).
    google_hosted_domain: str | None = None
    oauth_flow_ttl_minutes: int = 10

    @property
    def google_enabled(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_client_secret.get_secret_value()
            and self.google_redirect_uri
        )

    @property
    def artifact_search(self) -> ArtifactSearch:
        return ArtifactSearch(repo_root=self.repo_root, models_dir=self.models_dir)

    @property
    def config_dir(self) -> Path:
        return self.repo_root / "data/configs"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
