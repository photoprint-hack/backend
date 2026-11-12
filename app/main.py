import logging
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.exceptions import (
    ApiError,
    handle_api_error,
    handle_database,
    handle_http,
    handle_unknown,
    handle_validation,
)
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.schemas.shared.errors import ErrorEnvelope


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    config = get_settings()
    configure_logging()
    app = FastAPI(
        title=config.app_name,
        version=config.app_version,
        lifespan=lifespan,
        responses={status: {"model": ErrorEnvelope} for status in [400, 401, 403, 404, 409, 422, 500, 503]},
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Idempotency-Replayed"],
    )
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(HTTPException, handle_http)
    app.add_exception_handler(IntegrityError, handle_database)
    app.add_exception_handler(OperationalError, handle_database)
    app.add_exception_handler(Exception, handle_unknown)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        try:
            identifier = UUID(request.headers.get("X-Request-ID", ""))
        except ValueError:
            identifier = uuid4()
        request.state.request_id = identifier
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            response = await handle_unknown(request, exc)
        response.headers["X-Request-ID"] = str(identifier)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logging.getLogger("photoprint.requests").info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000, 2),
                "request_id": str(identifier),
            },
        )
        return response

    app.include_router(health_router, prefix="/health")
    app.include_router(api_router, prefix="/api/v1")
    if config.app_env != "production":
        from app.api.v1.demo import router as demo_router

        app.include_router(demo_router, prefix="/api/v1")
    return app


app = create_app()
