from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema


class ForecastWeek(Schema):
    week_start: date
    week_end: date
    demand: float | None
    available_capacity: float | None
    deficit: float | None
    reserve: float | None
    utilization_percent: float | None
    is_deficit: bool | None
    status: Literal["normal", "deficit", "no_data"]


class Forecast(Schema):
    status: Literal["ready", "no_data"]
    reason: str | None
    method: Literal["four_week_average"]
    unit: Literal["standard_hour"]
    as_of: date
    generated_at: datetime
    department_id: UUID | None
    product_id: UUID | None
    horizon_weeks: Literal[4]
    history_from: date
    history_to: date
    items: list[ForecastWeek]
    first_deficit_week: date | None
