from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.schemas.analytics.forecast import Forecast
from app.schemas.common import Data, Schema
from app.services.forecast import compute

router = APIRouter(tags=["forecast"])


class ForecastQuery(Schema):
    department_id: UUID | None = None
    product_id: UUID | None = None
    weeks: Literal[4] = 4


@router.get("/forecast", response_model=Data[Forecast])
async def forecast(db: DB, user: CurrentUser, query: Annotated[ForecastQuery, Query()]):
    result = await compute(db, user, query.department_id, query.product_id, persist=True)
    await db.commit()
    return {"data": result}
