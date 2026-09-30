"""FastAPI application factory. Run with: uvicorn twin_api.app:create_app --factory"""

from __future__ import annotations

from fastapi import FastAPI
from twin_core.twin import TwinConfigs

from twin_api import errors
from twin_api.db import make_engine, make_sessionmaker
from twin_api.routers import insights, oauth, patients, system
from twin_api.service import RuntimeHolder, TwinService
from twin_api.settings import Settings, get_settings

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Glycemic Digital Twin API",
        version="0.5.0",
        description=(
            "Serves the per-person glycemic Digital Twin (twin_core) over CGMacros data. "
            "Research prototype; model-estimated associations, not medical advice."
        ),
        docs_url=f"{API_PREFIX}/docs" if settings.environment != "production" else None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    engine = make_engine(settings.database_url)
    configs = TwinConfigs.load(settings.config_dir)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.configs = configs
    app.state.twin_service = TwinService(
        configs, RuntimeHolder(configs, settings.artifact_search), settings.source_label
    )
    errors.install(app)
    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(patients.router, prefix=API_PREFIX)
    app.include_router(insights.router, prefix=API_PREFIX)
    app.include_router(oauth.router, prefix=API_PREFIX)
    return app
