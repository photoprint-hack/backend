from uuid import UUID

from app.schemas.common import Schema


class ErrorDetail(Schema):
    code: str
    message: str
    fields: dict[str, str]
    request_id: UUID


class ErrorEnvelope(Schema):
    detail: ErrorDetail
