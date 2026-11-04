"""One error shape for every route, and the translation from service errors."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..app.errors import TaskConflict


LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """A failure this boundary decided, with the HTTP status it deserves."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def invalid(message: str) -> ApiError:
    return ApiError(400, "invalid_request", message)


def not_found(message: str = "That record was not found.") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def credential_missing() -> ApiError:
    return ApiError(
        409,
        "credential_missing",
        "No OpenAI API key is configured. Add one in settings before calling a model.",
    )


def provider_failed(message: str) -> ApiError:
    return ApiError(502, "provider_failed", message)


def _body(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": None}},
    )


def _validation_message(exc: RequestValidationError) -> str:
    """Report the first offending field, without echoing the submitted value."""
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = str(error.get("msg", "Invalid request."))
        return f"{location}: {message}" if location else message
    return "Invalid request."


def install(app: FastAPI) -> None:
    """Register handlers; the most specific exception type wins."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _body(exc.status_code, exc.code, exc.message)

    @app.exception_handler(TaskConflict)
    async def _task_conflict(_: Request, exc: TaskConflict) -> JSONResponse:
        return _body(409, "conflict", str(exc))

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return _body(400, "invalid_request", str(exc))

    @app.exception_handler(FileNotFoundError)
    async def _file_missing(_: Request, exc: FileNotFoundError) -> JSONResponse:
        # The service's message contains an id, never a path; keep it.
        return _body(404, "not_found", str(exc) or "That record was not found.")

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _body(400, "invalid_request", _validation_message(exc))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API failure.", exc_info=exc)
        return _body(500, "internal_error", "The request could not be completed.")
