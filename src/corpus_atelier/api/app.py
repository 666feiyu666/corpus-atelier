"""Compose the FastAPI application around the task runtime."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from . import errors
from .routes_corpus import router as corpus_router
from .routes_images import router as images_router
from .routes_settings import router as settings_router
from .routes_tasks import router as tasks_router
from .runtime import TaskRuntime


LOGGER = logging.getLogger(__name__)

DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def _origins() -> list[str]:
    raw = os.environ.get("CORPUS_ATELIER_API_ORIGINS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or list(DEFAULT_ORIGINS)


def create_app(
    *,
    runtime: TaskRuntime | None = None,
    resume: bool = True,
    origins: list[str] | None = None,
) -> FastAPI:
    """Build the API application; a caller may inject a runtime (tests do)."""
    runtime = runtime or TaskRuntime()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if resume:
            try:
                resumed = runtime.resume_recoverable()
            except Exception:
                LOGGER.exception("Could not resume recoverable tasks.")
            else:
                if resumed:
                    LOGGER.info("Resumed %s interrupted task(s).", resumed)
        try:
            yield
        finally:
            runtime.shutdown()

    app = FastAPI(
        title="Corpus Atelier API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins if origins is not None else _origins()),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Corpus-Seeded"],
    )
    errors.install(app)
    for router in (tasks_router, images_router, corpus_router, settings_router):
        app.include_router(router)

    @app.get("/api/v1/health", tags=["health"])
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "credential_configured": runtime.credential() is not None,
        }

    return app
