import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import DatabaseNotConfiguredError, get_engine

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Application starting",
            extra={"event": "application_starting", "environment": app_settings.environment},
        )
        try:
            yield
        finally:
            if app_settings.database_url is not None:
                get_engine(
                    app_settings.database_url,
                    app_settings.database_connect_timeout_seconds,
                ).dispose()
            logger.info(
                "Application stopped",
                extra={"event": "application_stopped", "environment": app_settings.environment},
            )

    application = FastAPI(
        title=app_settings.app_name,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.include_router(health_router)

    @application.exception_handler(DatabaseNotConfiguredError)
    async def database_not_configured(
        request: Request,
        _: DatabaseNotConfiguredError,
    ) -> JSONResponse:
        logger.error(
            "Database URL is not configured",
            extra={"event": "database_configuration_missing", "path": request.url.path},
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is not configured"},
        )

    return application


app = create_app()