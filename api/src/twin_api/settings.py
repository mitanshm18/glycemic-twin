"""Runtime settings, read from the environment (and a local, gitignored .env). No secret defaults.

Production (TWIN_ENVIRONMENT=production) refuses to start with an unsafe configuration: cookies
without Secure, no trusted host list, a partial or non-HTTPS Google sign-in setup. The rules live
in ``_production_rules`` and are listed in docs/security.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from twin_api.registry import ArtifactSearch

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # hide_input_in_errors: a configuration error names the problem, never the values (URLs with
    # passwords, client secrets), so startup failures can be logged safely
    model_config = SettingsConfigDict(
        env_prefix="TWIN_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # postgresql+psycopg://user:password@host:5432/dbname  (required; never committed). A secret:
    # it holds the database password, so it never appears in reprs, logs or error messages.
    database_url: SecretStr = Field(..., description="SQLAlchemy URL of the PostgreSQL database")
    repo_root: Path = REPO_ROOT
    # Where serving finds registered model bundles by file name (containers, servers). Optional:
    # without it serving uses the registered path, then repo_root/data/processed/m3/models.
    models_dir: Path | None = None
    environment: Literal["development", "test", "production"] = "development"
    # Host names this API answers for (TWIN_TRUSTED_HOSTS, comma-separated, e.g.
    # "twin.example.org,api,localhost"). Required in production; requests for any other Host
    # header get 400. Unset outside production means "any host" (local development).
    trusted_hosts: str | None = None
    session_ttl_minutes: int = Field(default=8 * 60, ge=5, le=24 * 60)
    cookie_name: str = Field(default="twin_session", pattern=r"^[A-Za-z0-9_-]+$")
    cookie_secure: bool = True  # set TWIN_COOKIE_SECURE=false only for local http development
    max_failed_logins: int = Field(default=5, ge=1, le=20)
    lockout_minutes: int = Field(default=15, ge=1)
    source_label: str = "CGMacros v1.0.0 (processed by M1/M2)"
    # Operational logs (stderr). json: one object per line, for containers and log collectors;
    # text: readable lines for local development. Unset means json in production, text otherwise.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] | None = None

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
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def log_style(self) -> Literal["json", "text"]:
        return self.log_format or ("json" if self.production else "text")

    @property
    def trusted_host_list(self) -> list[str]:
        return [h.strip() for h in (self.trusted_hosts or "").split(",") if h.strip()]

    @model_validator(mode="after")
    def _production_rules(self) -> Settings:
        if not self.production:
            return self
        problems = []
        if not self.cookie_secure:
            problems.append("TWIN_COOKIE_SECURE must be true (session cookies only over HTTPS)")
        if not self.trusted_host_list:
            problems.append("TWIN_TRUSTED_HOSTS must list the public host name(s)")
        elif "*" in self.trusted_host_list:
            problems.append("TWIN_TRUSTED_HOSTS must not contain '*'")
        google = [self.google_client_id, self.google_client_secret, self.google_redirect_uri]
        if any(google) and not self.google_enabled:
            problems.append(
                "Google sign-in is partly configured: set all of TWIN_GOOGLE_CLIENT_ID, "
                "TWIN_GOOGLE_CLIENT_SECRET and TWIN_GOOGLE_REDIRECT_URI, or none"
            )
        if self.google_redirect_uri and urlsplit(self.google_redirect_uri).scheme != "https":
            problems.append("TWIN_GOOGLE_REDIRECT_URI must use https")
        if problems:
            raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

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
