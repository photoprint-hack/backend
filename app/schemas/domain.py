"""Compatibility exports; definitions live in domain modules."""

from app.schemas.analytics.alerts import AlertPatch, AlertsQuery
from app.schemas.analytics.metrics import BreakdownQuery, HistoryQuery, MetricsQuery
from app.schemas.catalog.campaigns import CampaignsQuery
from app.schemas.catalog.customers import CustomersQuery
from app.schemas.catalog.products import ProductsQuery
from app.schemas.catalog.sales import DealsQuery
from app.schemas.reporting.production import ProductionQuery, QueueQuery
from app.schemas.reporting.support import SupportQuery
from app.schemas.shared.query import AnalyticsQuery, BusinessQuery, DateRange, PaginationQuery, SearchQuery
from app.schemas.shared.references import NamedRef, UserRef
from app.schemas.workflow.common import Priority, VersionedPatch
from app.schemas.workflow.decisions import (
    DecisionCreate,
    DecisionOut,
    DecisionPatch,
    DecisionsQuery,
    DecisionStatus,
)
from app.schemas.workflow.orders import OrderCreate, OrderOut, OrderPatch, OrdersQuery, OrderStatus
from app.schemas.workflow.tasks import TaskCreate, TaskOut, TaskPatch, TasksQuery, TaskStatus

__all__ = [
    "AlertPatch",
    "AlertsQuery",
    "AnalyticsQuery",
    "BreakdownQuery",
    "BusinessQuery",
    "CampaignsQuery",
    "CustomersQuery",
    "DateRange",
    "DealsQuery",
    "DecisionCreate",
    "DecisionOut",
    "DecisionPatch",
    "DecisionStatus",
    "DecisionsQuery",
    "HistoryQuery",
    "MetricsQuery",
    "NamedRef",
    "OrderCreate",
    "OrderOut",
    "OrderPatch",
    "OrderStatus",
    "OrdersQuery",
    "PaginationQuery",
    "Priority",
    "ProductionQuery",
    "ProductsQuery",
    "QueueQuery",
    "SearchQuery",
    "SupportQuery",
    "TaskCreate",
    "TaskOut",
    "TaskPatch",
    "TaskStatus",
    "TasksQuery",
    "UserRef",
    "VersionedPatch",
]
