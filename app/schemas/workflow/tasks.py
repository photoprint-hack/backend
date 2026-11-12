from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.schemas.common import Schema, TextValue, Title
from app.schemas.shared.query import DateRange, SearchQuery
from app.schemas.shared.references import NamedRef, UserRef
from app.schemas.workflow.common import Priority, VersionedPatch

TaskStatus = Literal["new", "in_progress", "completed", "cancelled"]


class TasksQuery(SearchQuery, DateRange):
    mine: bool | None = None
    department_id: UUID | None = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    assignee_id: UUID | None = None
    decision_id: UUID | None = None
    alert_id: UUID | None = None
    order_id: UUID | None = None
    overdue: bool | None = None


class TaskCreate(Schema):
    title: Title
    description: Annotated[str, Field(max_length=5000)] = ""
    assignee_id: UUID
    department_id: UUID
    deadline: AwareDatetime
    priority: Priority
    decision_id: UUID | None = None
    alert_id: UUID | None = None
    order_id: UUID | None = None


class TaskPatch(VersionedPatch):
    title: Title | None = None
    description: Annotated[str, Field(max_length=5000)] | None = None
    assignee_id: UUID | None = None
    deadline: AwareDatetime | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    comment: TextValue | None = None


class TaskOut(Schema):
    id: UUID
    title: str
    description: str
    assignee_id: UUID
    assignee: UserRef
    created_by: UUID
    creator: UserRef
    department_id: UUID
    department: NamedRef
    decision_id: UUID | None
    decision: NamedRef | None
    alert_id: UUID | None
    alert_title: str | None = None
    order_id: UUID | None
    deadline: datetime
    priority: Priority
    status: TaskStatus
    is_overdue: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    version: int
    allowed_actions: list[str]
