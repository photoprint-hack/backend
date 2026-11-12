from datetime import date, datetime
from uuid import UUID

from app.schemas.analytics.alerts import AlertOut
from app.schemas.analytics.metrics import Kpi
from app.schemas.common import Schema
from app.schemas.workflow.decisions import DecisionOut
from app.schemas.workflow.tasks import TaskOut


class Dashboard(Schema):
    period: dict[str, date]
    filters: dict[str, UUID | None]
    kpis: list[Kpi]
    active_alerts_count: int
    critical_alerts_count: int
    active_decisions_count: int
    active_tasks_count: int
    overdue_tasks_count: int
    recent_alerts: list[AlertOut]
    recent_decisions: list[DecisionOut]
    recent_tasks: list[TaskOut]
    updated_at: datetime
