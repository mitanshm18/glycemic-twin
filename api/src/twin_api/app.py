"""FastAPI application factory. Run with: uvicorn twin_api.app:create_app --factory"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from twin_core.twin import TwinConfigs

from twin_api import errors
from twin_api.db import make_engine, make_sessionmaker
from twin_api.logs import RequestLog, configure_logging
from twin_api.routers import insights, oauth, patients, system
from twin_api.service import RuntimeHolder, TwinService
from twin_api.settings import Settings, get_settings

API_PREFIX = "/api/v1"
log = logging.getLogger("twin_api")

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


def lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Startup / shutdown lines: what this process serves, never a secret."""

    @asynccontextmanager
    async def run(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "api starting",
            extra={
                "fields": {
                    "event": "startup",
                    "version": app.version,
                    "environment": settings.environment,
                    "trusted_hosts": settings.trusted_host_list,
                    "google_sign_in": settings.google_enabled,
                    "models_dir": str(settings.models_dir) if settings.models_dir else None,
                }
            },
        )
        yield
        app.state.engine.dispose()
        log.info("api stopped", extra={"fields": {"event": "shutdown"}})

    return run


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.environment != "test":
        # also here, not only in `twin-api serve`: uvicorn's reloader and `uvicorn --factory`
        # build the app in a process that never ran the CLI (idempotent)
        configure_logging(settings.log_level, settings.log_style)
    app = FastAPI(
        lifespan=lifespan(settings),
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
    # added last = outermost: every request gets an id and one log line, whatever happens inside
    app.add_middleware(RequestLog)
    return app
