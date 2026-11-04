"""Compose the FastAPI application around the task runtime."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config.paths import PROJECT_ROOT
from . import errors
from .routes_corpus import router as corpus_router
from .routes_images import router as images_router
from .routes_settings import router as settings_router
from .routes_tasks import router as tasks_router
from .runtime import TaskRuntime


LOGGER = logging.getLogger(__name__)

SERVICE_NAME = "corpus-atelier"

# The header every response carries, so the interface can tell this API from
# whatever else might be answering on the same port.
SERVICE_HEADER = "X-Corpus-Atelier"

# Any loopback origin, on any port. The interface keeps a fixed port, but a dev
# server that steps to another port must still reach the API rather than fail
# with an opaque CORS error. Non-loopback origins stay refused.
LOOPBACK_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1|\[::1\]):\d+$"


def _origins() -> list[str]:
    raw = os.environ.get("CORPUS_ATELIER_API_ORIGINS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values


def _profile_name() -> str:
    """The running profile, matching the roots ``resolve_paths`` would pick."""
    return "dev" if os.environ.get("CORPUS_ATELIER_PROFILE", "").strip().lower() == "dev" else "daily"


def interface_directory() -> Path | None:
    """The built SPA, when one exists.

    This is what lets daily use be a single process: the interface is static, so
    the API can serve it from its own origin instead of a second dev server.
    """
    override = os.environ.get("CORPUS_ATELIER_INTERFACE_DIR")
    directory = Path(override) if override else PROJECT_ROOT / "web" / ".output" / "public"
    return directory if (directory / "index.html").is_file() else None


def _mount_interface(app: FastAPI, directory: Path) -> None:
    """Serve the SPA beside the API, falling back to index.html for its routes."""
    root = directory.resolve()
    assets = root / "_nuxt"
    if assets.is_dir():
        app.mount("/_nuxt", StaticFiles(directory=assets), name="nuxt-assets")
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def serve_interface(path: str) -> FileResponse:
        # Unknown API paths must stay API errors, not the SPA shell.
        if path == "api" or path.startswith("api/"):
            raise errors.not_found("That endpoint does not exist.")
        if path:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index)


def create_app(
    *,
    runtime: TaskRuntime | None = None,
    resume: bool = True,
    origins: list[str] | None = None,
    interface_dir: Path | None = None,
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
    allowed = origins if origins is not None else _origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed),
        allow_origin_regex=None if allowed else LOOPBACK_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Corpus-Seeded", SERVICE_HEADER],
    )

    @app.middleware("http")
    async def identify_service(request, call_next):
        """Stamp the service name on every response, errors included."""
        response = await call_next(request)
        response.headers[SERVICE_HEADER] = SERVICE_NAME
        return response

    errors.install(app)
    for router in (tasks_router, images_router, corpus_router, settings_router):
        app.include_router(router)

    @app.get("/api/v1/health", tags=["health"])
    def health() -> dict:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "profile": _profile_name(),
            "version": __version__,
            "credential_configured": runtime.credential() is not None,
        }

    if interface_dir is not None and (interface_dir / "index.html").is_file():
        _mount_interface(app, interface_dir)

    return app
