"""Compatibility exports; definitions live in domain modules."""

from app.schemas.analytics.alerts import AlertCard, AlertOut
from app.schemas.analytics.dashboard import Dashboard
from app.schemas.analytics.forecast import Forecast, ForecastWeek
from app.schemas.analytics.metrics import (
    BreakdownPage,
    BreakdownRow,
    Context,
    Kpi,
    MetricHistoryPage,
    MetricPoint,
    RecalculateResult,
)
from app.schemas.catalog.campaigns import CampaignOut
from app.schemas.catalog.customers import CustomerCard, CustomerOut
from app.schemas.catalog.products import ProductOut
from app.schemas.catalog.sales import DealOut, Funnel, FunnelStage, SalesSlice, SalesSummary
from app.schemas.integrations.imports import ImportErrorOut, ImportResult, ImportRun, SourceStatus
from app.schemas.integrations.quality import (
    FinancialSource,
    QualityCheckResult,
    QualityIssue,
    QualityOverview,
    Reconciliation,
)
from app.schemas.reporting.finance import BDDS, BDR, FinanceSummary, PlanFact
from app.schemas.reporting.hr import HRSummary
from app.schemas.reporting.production import ProductionOut, ProductionSummary
from app.schemas.reporting.support import SupportOut
from app.schemas.shared.errors import ErrorDetail, ErrorEnvelope
from app.schemas.shared.events import AuditOut, ChangeEvent
from app.schemas.shared.references import Link, NamedObject, UserRef
from app.schemas.workflow.orders import OrderEventOut

__all__ = [
    "AlertCard",
    "AlertOut",
    "AuditOut",
    "BDDS",
    "BDR",
    "BreakdownPage",
    "BreakdownRow",
    "CampaignOut",
    "ChangeEvent",
    "Context",
    "CustomerCard",
    "CustomerOut",
    "Dashboard",
    "DealOut",
    "ErrorDetail",
    "ErrorEnvelope",
    "FinanceSummary",
    "FinancialSource",
    "Forecast",
    "ForecastWeek",
    "Funnel",
    "FunnelStage",
    "HRSummary",
    "ImportErrorOut",
    "ImportResult",
    "ImportRun",
    "Kpi",
    "Link",
    "MetricHistoryPage",
    "MetricPoint",
    "NamedObject",
    "OrderEventOut",
    "PlanFact",
    "ProductOut",
    "ProductionOut",
    "ProductionSummary",
    "QualityCheckResult",
    "QualityIssue",
    "QualityOverview",
    "RecalculateResult",
    "Reconciliation",
    "SalesSlice",
    "SalesSummary",
    "SourceStatus",
    "SupportOut",
    "UserRef",
]
