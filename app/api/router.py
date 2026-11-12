from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.data_quality import router as data_quality_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.imports import router as imports_router
from app.api.v1.summaries import router as summaries_router
from app.api.v1.users import router as users_router
from app.api.v1.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)


api_router.include_router(workflow_router)

api_router.include_router(analytics_router)

api_router.include_router(catalog_router)

api_router.include_router(summaries_router)

api_router.include_router(forecast_router)

api_router.include_router(data_quality_router)
api_router.include_router(imports_router)

api_router.include_router(audit_router)

from app.api.v1.impact import router as impact_router  # noqa: E402

api_router.include_router(impact_router)

from app.api.v1.mock_sources import router as mock_sources_router  # noqa: E402

api_router.include_router(mock_sources_router)
