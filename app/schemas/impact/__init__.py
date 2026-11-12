from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import Schema, TextValue, Title
from app.schemas.shared.query import BusinessQuery, PaginationQuery
from app.schemas.workflow.common import Priority

ActionType = Literal["reminder", "explanation_request", "task"]
ActionStatus = Literal[
    "draft", "sent", "acknowledged", "in_progress", "resolved", "verified", "rejected", "cancelled"
]
Direction = Literal["in", "out", "both"]
EdgeType = Literal["feeds", "belongs_to", "depends_on", "may_affect", "produces", "mitigated_by"]
NodeType = Literal["source", "department", "process", "entity", "event", "metric", "risk", "decision"]


class EntityRef(Schema):
    type: Literal["metric", "order", "task", "decision", "alert", "department", "mary_event", "order_event"]
    id: str


class Node(Schema):
    id: UUID
    type: NodeType
    label: str
    description: str
    entity_ref: EntityRef | None = None
    status: str | None = None
    context: dict
    updated_at: datetime | None = None
    allowed_actions: list[str]
    metadata: dict = {}  # noqa: RUF012


class Edge(Schema):
    id: UUID
    source: UUID
    target: UUID
    type: EdgeType
    evidence_type: Literal["verified", "calculated", "correlated", "hypothesis"]
    description: str
    evidence_source: str
    evidence_refs: list[UUID]


class Graph(Schema):
    nodes: list[Node]
    edges: list[Edge]
    context: dict
    graph_revision: str
    generated_at: datetime
    truncated: bool


class NeighborsQuery(BusinessQuery):
    depth: Annotated[int, Field(ge=1, le=3)] = 1
    direction: Direction = "both"
    edge_types: list[EdgeType] = []  # noqa: RUF012


class PathsQuery(BusinessQuery):
    from_node_id: UUID
    to_node_id: UUID
    depth: Annotated[int, Field(ge=1, le=3)] = 3
    direction: Direction = "out"
    edge_types: list[EdgeType] = []  # noqa: RUF012


class ActionCreate(Schema):
    type: ActionType
    department_id: UUID
    title: Title
    text: TextValue
    priority: Priority = "medium"
    assignee_id: UUID | None = None
    metric_code: str | None = None
    source_ref: EntityRef | None = None
    context: BusinessQuery
    decision_id: UUID | None = None
    alert_id: UUID | None = None
    order_id: UUID | None = None
    task_id: UUID | None = None
    execution_due_at: AwareDatetime | None = None


class ActionPatch(Schema):
    version: Annotated[int, Field(ge=1)]
    title: Title | None = None
    text: TextValue | None = None
    priority: Priority | None = None
    assignee_id: UUID | None = None
    execution_due_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def nonnull(self):
        if any(
            getattr(self, key) is None for key in self.model_fields_set - {"assignee_id", "execution_due_at"}
        ):
            raise ValueError("Field cannot be null")
        return self


class ActionCommand(Schema):
    response_due_at: AwareDatetime | None = None
    version: Annotated[int, Field(ge=1)]
    reason: TextValue | None = None
    result: TextValue | None = None
    result_refs: Annotated[list[EntityRef], Field(max_length=20)] = []  # noqa: RUF012
    verification_note: TextValue | None = None
    assignee_id: UUID | None = None
    execution_due_at: AwareDatetime | None = None


class ActionsQuery(PaginationQuery):
    department_id: UUID | None = None
    status: ActionStatus | None = None
    assignee_id: UUID | None = None
    type: ActionType | None = None


class ActionOut(Schema):
    id: UUID
    type: ActionType
    status: ActionStatus
    version: int
    author_id: UUID
    assignee_id: UUID | None
    department_id: UUID
    title: str
    text: str
    priority: Priority
    metric_code: str | None
    source_ref: EntityRef | None
    context: dict
    decision_id: UUID | None
    alert_id: UUID | None
    order_id: UUID | None
    task_id: UUID | None
    response_due_at: datetime | None
    execution_due_at: datetime | None
    execution_status: str | None
    calendar_version: str | None
    assignment_cycle: int
    escalation_level: int
    sent_at: datetime | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    verified_at: datetime | None
    reviewer_id: UUID | None
    result: str | None
    result_refs: list[EntityRef]
    verification_note: str | None
    routing_issue: str | None
    response_overdue: bool
    response_was_late: bool
    execution_overdue: bool
    allowed_actions: list[str]
    created_at: datetime
    updated_at: datetime


class DepartmentAssignment(Schema):
    head_id: UUID
    director_id: UUID
    version: Annotated[int, Field(ge=0)]


class MetricAssignment(Schema):
    department_id: UUID | None = None
    owner_id: UUID
    version: Annotated[int, Field(ge=0)]


class NotificationOut(Schema):
    id: UUID
    action_id: UUID
    kind: str
    created_at: datetime
    delivered_at: datetime | None
    read_at: datetime | None


class NotificationsQuery(PaginationQuery):
    unread: bool | None = None


class Analyze(Schema):
    request_key: UUID
    metric_code: str
    context: BusinessQuery
    graph_revision: str


class AnalysisItem(Schema):
    text: TextValue
    refs: Annotated[list[str], Field(max_length=20)]


class AnalysisContent(Schema):
    summary: TextValue
    changes: Annotated[list[AnalysisItem], Field(max_length=20)]
    verified_facts: Annotated[list[AnalysisItem], Field(max_length=20)]
    calculated_dependencies: Annotated[list[AnalysisItem], Field(max_length=20)]
    correlations: Annotated[list[AnalysisItem], Field(max_length=20)]
    hypotheses: Annotated[list[AnalysisItem], Field(max_length=20)]
    possible_impacts: Annotated[list[AnalysisItem], Field(max_length=20)]
    recommendations: Annotated[list[AnalysisItem], Field(max_length=20)]
    data_gaps: Annotated[list[AnalysisItem], Field(max_length=20)]
    suggested_responsible: str | None
    draft_text: Annotated[str, Field(max_length=5000)]


class AnalysisOut(Schema):
    id: UUID
    analysis: AnalysisContent
    context: dict
    graph_revision: str
    model: str
    generated_at: datetime
    cached: bool
    ai_generated: Literal[True] = True


class MaryRecord(Schema):
    external_id: Annotated[str, Field(min_length=1, max_length=200)]
    event_type: Literal[
        "conversation_started",
        "conversation_resolved",
        "conversation_handoff",
        "lead_qualified",
        "order_intent_detected",
    ]
    occurred_at: AwareDatetime
    department_id: UUID
    order_id: UUID | None = None
    # Deliberate allowlist: no transcripts, customer identity or arbitrary nested fields.
    channel: Literal["web", "phone", "demo"] = "demo"


class MaryBatch(Schema):
    records: Annotated[list[MaryRecord], Field(min_length=1, max_length=1000)]
