import logging
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, fields: dict | None = None, *, clear_refresh: bool = False
    ):
        self.status, self.code, self.message = status, code, message
        self.fields = fields or {}
        self.clear_refresh = clear_refresh


def error_response(
    request: Request, status: int, code: str, message: str, fields: dict | None = None
) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", uuid4()))
    headers = {"X-Request-ID": request_id}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status,
        content={
            "detail": {"code": code, "message": message, "fields": fields or {}, "request_id": request_id}
        },
        headers=headers,
    )


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    if exc.status in {403, 409, 422} and getattr(request.state, "actor_id", None):
        await failure_audit(request, exc.status, exc.code)
    response = error_response(request, exc.status, exc.code, exc.message, exc.fields)
    if exc.clear_refresh:
        from app.core.config import get_settings

        config = get_settings()
        response.delete_cookie(
            "refresh_token",
            path="/api/v1/auth",
            secure=config.cookie_secure,
            httponly=True,
            samesite=config.cookie_samesite,
        )
    return response


async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    if getattr(request.state, "actor_id", None):
        await failure_audit(request, 422, "VALIDATION_ERROR")
    fields = {
        ".".join(str(part) for part in e["loc"] if part not in ("body", "query")): e["msg"]
        for e in exc.errors()
    }
    return error_response(request, 422, "VALIDATION_ERROR", "Проверьте переданные данные", fields)


async def handle_http(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {
        400: "BAD_REQUEST",
        401: "AUTH_TOKEN_EXPIRED",
        403: "AUTH_FORBIDDEN",
        404: "RESOURCE_NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        413: "PAYLOAD_TOO_LARGE",
        503: "DATA_SOURCE_UNAVAILABLE",
    }
    return error_response(
        request, exc.status_code, codes.get(exc.status_code, "BAD_REQUEST"), "Запрос не может быть выполнен"
    )


async def handle_database(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, IntegrityError):
        # Preserve the exact constraint failure for diagnostics without leaking SQL parameters.
        logging.getLogger("photoprint.db").warning(
            "Integrity error sqlstate=%s request_id=%s",
            getattr(exc.orig, "sqlstate", None),
            getattr(request.state, "request_id", ""),
        )
        return error_response(request, 409, "DUPLICATE_RESOURCE", "Конфликт или нарушение целостности данных")
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "База данных временно недоступна")


async def handle_unknown(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("photoprint").error(
        "Unhandled exception type=%s request_id=%s",
        type(exc).__name__,
        getattr(request.state, "request_id", ""),
    )
    return error_response(request, 500, "INTERNAL_SERVER_ERROR", "Внутренняя ошибка сервера")


async def failure_audit(request: Request, status: int, code: str):
    try:
        from app.db.session import get_session_factory
        from app.models import User
        from app.services.audit import record

        factory = getattr(request.state, "session_factory", None) or get_session_factory()
        pieces = request.url.path.split("/")
        object_type = {"orders": "order", "tasks": "task", "decisions": "decision", "alerts": "alert"}.get(
            pieces[3] if len(pieces) > 3 else "", "request"
        )
        try:
            object_id = UUID(pieces[4]) if len(pieces) > 4 else None
        except ValueError:
            object_id = None
        async with factory() as db:
            actor = await db.get(User, request.state.actor_id)
            record(
                db,
                "access.denied" if status == 403 else "operation.failed",
                object_type,
                actor=actor,
                object_id=object_id,
                status="failure",
                details={"code": code},
                request=request,
            )
            await db.commit()
    except Exception:
        # Denial never becomes success if its independent audit cannot be saved.
        logging.getLogger("photoprint.audit").error(
            "Failure audit could not be persisted",
            extra={"request_id": str(getattr(request.state, "request_id", "")), "status_code": status},
        )
