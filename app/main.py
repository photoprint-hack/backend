from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Startup hooks can be added here. The engine connects lazily.
    yield
    # Shutdown: release pooled connections.
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan,
    )
    application.include_router(health_router, prefix="/health")
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
