from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]
Hours = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=4),
    PlainSerializer(float, return_type=float, when_used="json"),
]
Title = Annotated[str, Field(min_length=1, max_length=200)]
TextValue = Annotated[str, Field(min_length=1, max_length=5000)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class Data[T](Schema):
    data: T


class Page[T](Schema):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


def page(items: list, total: int, page_number: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page_number,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }
