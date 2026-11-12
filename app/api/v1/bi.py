from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

import jwt
from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.schemas.analytics.bi import BIEmbed
from app.schemas.common import Data
from app.schemas.shared.query import BusinessQuery
from app.services.analytics import period

router = APIRouter(tags=["BI"])


class BIQuery(BusinessQuery):
    dashboard: Literal["company", "production", "finance", "support", "hr"] = "company"


@router.get("/analytics/metabase-embed", response_model=Data[BIEmbed])
async def embed(user: CurrentUser, query: Annotated[BIQuery, Query()]):
    require_role(user, READ_ROLES)
    config = get_settings()
    department = department_scope(user, query.department_id)
    dashboard_id = config.metabase_dashboard_ids.get(query.dashboard)
    # Deployment must explicitly attest which dashboards have all locked filters wired and tested.
    verified = getattr(config, "metabase_verified_dashboards", [])
    if (
        not config.metabase_url
        or not config.metabase_embedding_secret
        or dashboard_id is None
        or query.dashboard not in verified
    ):
        raise ApiError(503, "BI_UNAVAILABLE", "Защищённый BI-dashboard ещё не настроен и не проверен")
    parts = urlsplit(config.metabase_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.query
        or parts.fragment
        or config.app_env == "production"
        and parts.scheme != "https"
    ):
        raise ApiError(503, "BI_UNAVAILABLE", "Недопустимая конфигурация BI")
    if user.role == "manager" and department is None:
        raise ApiError(403, "DEPARTMENT_ACCESS_DENIED", "Подразделение обязательно")
    start, end, _, _ = period(query)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    params = {
        "department_id": str(department) if department else "company",
        "product_id": str(query.product_id) if query.product_id else "all",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
    }
    token = jwt.encode(
        {"resource": {"dashboard": dashboard_id}, "params": params, "exp": expires},
        config.metabase_embedding_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {
        "data": {
            "embed_url": config.metabase_url.rstrip("/")
            + "/embed/dashboard/"
            + token
            + "#bordered=false&titled=true",
            "expires_at": expires,
            "context": {
                "date_from": start,
                "date_to": end,
                "department_id": department,
                "product_id": query.product_id,
                "ignored_filters": ["product_id"] if query.dashboard == "hr" and query.product_id else [],
            },
        }
    }
