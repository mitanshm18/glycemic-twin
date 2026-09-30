"""One error shape for every failure: {"error": {"code", "message", "details"}}.

Messages never include stack traces, SQL or submitted values.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | dict[str, Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def patient_not_found(pid: int) -> ApiError:
    return ApiError(404, "PATIENT_NOT_FOUND", f"patient {pid} does not exist")


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} does not exist")


def invalid_timestamp(message: str) -> ApiError:
    return ApiError(422, "INVALID_TIMESTAMP", message)


def data_out_of_range(message: str, details: Any = None) -> ApiError:
    return ApiError(422, "DATA_OUT_OF_RANGE", message, details)


def no_current_meal(message: str) -> ApiError:
    return ApiError(409, "NO_CURRENT_MEAL", message)


def model_unavailable(message: str) -> ApiError:
    return ApiError(503, "MODEL_UNAVAILABLE", message)


def model_incompatible(message: str) -> ApiError:
    return ApiError(409, "MODEL_INCOMPATIBLE", message)


def what_if_unsupported(message: str) -> ApiError:
    return ApiError(422, "WHAT_IF_UNSUPPORTED", message)


def unauthenticated(message: str = "authentication required") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def forbidden(message: str = "not allowed for your role") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def csrf_failed() -> ApiError:
    return ApiError(403, "CSRF_FAILED", "missing or invalid X-CSRF-Token header")


def conflict(message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message)


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return ErrorBody(error=ErrorDetail(code=code, message=message, details=details)).model_dump()


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            _body("VALIDATION_ERROR", "request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(_body("INTERNAL_ERROR", "unexpected server error"), status_code=500)
