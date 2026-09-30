"""FastAPI application factory. Run with: uvicorn twin_api.app:create_app --factory"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from twin_core.twin import TwinConfigs

from twin_api import errors
from twin_api.db import make_engine, make_sessionmaker
from twin_api.routers import insights, oauth, patients, system
from twin_api.service import RuntimeHolder, TwinService
from twin_api.settings import Settings, get_settings

API_PREFIX = "/api/v1"

Handler = Callable[[Request], Awaitable[Response]]


def security_headers(production: bool) -> Callable[[Request, Handler], Awaitable[Response]]:
    """Headers on every API response: never cache patient data, never sniff, never frame.

    The API only returns JSON (and redirects), so in production it can also forbid every
    resource type outright. In development the interactive docs need their scripts.
    """

    async def add(request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("Cache-Control", "no-store")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("X-Frame-Options", "DENY")
        if production:
            h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response

    return add


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Glycemic Digital Twin API",
        version="0.5.0",
        description=(
            "Serves the per-person glycemic Digital Twin (twin_core) over CGMacros data. "
            "Research prototype; model-estimated associations, not medical advice."
        ),
        # interactive docs and the schema are for development only
        docs_url=None if settings.production else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if settings.production else f"{API_PREFIX}/openapi.json",
    )
    if settings.trusted_host_list:
        # a request for any other Host header is refused (400) before it reaches a route
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
    app.middleware("http")(security_headers(settings.production))
    engine = make_engine(settings.database_url.get_secret_value())
    configs = TwinConfigs.load(settings.config_dir)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.configs = configs
    app.state.twin_service = TwinService(
        configs,
        RuntimeHolder(configs, settings.artifact_search, detailed_errors=not settings.production),
        settings.source_label,
    )
    errors.install(app)
    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(patients.router, prefix=API_PREFIX)
    app.include_router(insights.router, prefix=API_PREFIX)
    app.include_router(oauth.router, prefix=API_PREFIX)
    return app
