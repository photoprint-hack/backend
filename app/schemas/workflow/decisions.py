from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from app.schemas.common import Schema, TextValue, Title
from app.schemas.shared.query import DateRange, SearchQuery
from app.schemas.shared.references import NamedRef, UserRef
from app.schemas.workflow.common import Priority, VersionedPatch

DecisionStatus = Literal["new", "in_progress", "needs_review", "completed", "cancelled"]


class DecisionsQuery(SearchQuery, DateRange):
    product_id: UUID | None = None
    department_id: UUID | None = None
    status: DecisionStatus | None = None
    priority: Priority | None = None
    owner_id: UUID | None = None
    alert_id: UUID | None = None
    deadline_from: AwareDatetime | None = None
    deadline_to: AwareDatetime | None = None
    overdue: bool | None = None


class DecisionCreate(Schema):
    title: Title
    problem: TextValue
    impact: TextValue
    cause: TextValue
    action: TextValue
    department_id: UUID | None
    owner_id: UUID
    alert_id: UUID | None = None
    deadline: AwareDatetime
    priority: Priority
    expected_result: TextValue


class DecisionPatch(VersionedPatch):
    title: Title | None = None
    problem: TextValue | None = None
    impact: TextValue | None = None
    cause: TextValue | None = None
    action: TextValue | None = None
    owner_id: UUID | None = None
    deadline: AwareDatetime | None = None
    priority: Priority | None = None
    expected_result: TextValue | None = None
    actual_result: TextValue | None = None
    verification_note: TextValue | None = None
    status: DecisionStatus | None = None
    comment: TextValue | None = None


class DecisionOut(Schema):
    id: UUID
    title: str
    problem: str
    impact: str
    cause: str
    action: str
    department_id: UUID | None
    department: NamedRef | None
    owner_id: UUID
    owner: UserRef
    created_by: UUID
    creator: UserRef
    alert_id: UUID | None
    alert_title: str | None = None
    deadline: datetime
    priority: Priority
    status: DecisionStatus
    expected_result: str
    actual_result: str | None
    verification_note: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    version: int
    allowed_actions: list[str]
