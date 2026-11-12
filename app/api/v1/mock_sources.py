from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.core.permissions import require_role
from app.schemas.common import Page, page
from app.schemas.integrations.mock_sources import MockRecord, MockSource
from app.schemas.shared.query import PaginationQuery
from app.services.mock_sources import records

router = APIRouter(tags=["mock-sources"])


@router.get("/mock-sources/{source}/records", response_model=Page[MockRecord])
async def mock_records(
    source: MockSource, db: DB, user: CurrentUser, query: Annotated[PaginationQuery, Query()]
):
    """Read database records as a simulated external source. Admin only; no writes."""
    require_role(user, {"admin"})
    items, total = await records(db, source, query.page, query.page_size)
    return page(items, total, query.page, query.page_size)
