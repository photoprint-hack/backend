from uuid import UUID

from app.schemas.common import Schema


class UserRef(Schema):
    id: UUID
    full_name: str


class NamedRef(Schema):
    id: UUID
    name: str


class NamedObject(Schema):
    id: UUID
    name: str


class Link(Schema):
    object_type: str
    object_id: UUID
    label: str
