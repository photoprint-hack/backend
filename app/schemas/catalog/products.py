from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.common import Schema
from app.schemas.shared.query import SearchQuery


class ProductsQuery(SearchQuery):
    category: str | None = None
    is_active: bool | None = None
    sort_by: str = "name"
    sort_order: Literal["asc", "desc"] = "asc"


class ProductOut(Schema):
    id: UUID
    external_id: str | None
    code: str
    name: str
    category: str
    standard_price: float
    currency: Literal["BYN"]
    standard_hours_per_unit: float
    is_active: bool
    created_at: datetime
