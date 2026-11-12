from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema


class DateRange(Schema):
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if (
            self.date_from
            and self.date_to
            and (self.date_to < self.date_from or (self.date_to - self.date_from).days > 365)
        ):
            raise ValueError("Некорректный диапазон дат (максимум 366 дней)")
        return self


class AnalyticsQuery(DateRange):
    department_id: UUID | None = None
    product_id: UUID | None = None


class PaginationQuery(Schema):
    page: Annotated[int, Field(ge=1)] = 1
    page_size: Annotated[int, Field(ge=1, le=100)] = 20


class SearchQuery(PaginationQuery):
    search: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


BusinessQuery = AnalyticsQuery
