from app.models.analytics import (
    Alert,
    FinanceRecord,
    ForecastRecord,
    HRSnapshot,
    Metric,
    MetricTarget,
    MetricValue,
)
from app.models.identity import Department, RefreshToken, User
from app.models.operations import (
    AuditLog,
    DataQualityIssue,
    DataQualityRun,
    IdempotencyKey,
    SourceRecord,
    SourceSyncRun,
)
from app.models.orders import (
    Campaign,
    CapacityPlan,
    Customer,
    Deal,
    DealEvent,
    Order,
    OrderEvent,
    Product,
    ProductionRecord,
    SupportInteraction,
)
from app.models.workflow import Decision, DecisionHistory, Task

__all__ = [
    "Alert",
    "FinanceRecord",
    "ForecastRecord",
    "HRSnapshot",
    "Metric",
    "MetricTarget",
    "MetricValue",
    "Department",
    "RefreshToken",
    "User",
    "AuditLog",
    "DataQualityIssue",
    "DataQualityRun",
    "IdempotencyKey",
    "SourceRecord",
    "SourceSyncRun",
    "Campaign",
    "CapacityPlan",
    "Customer",
    "Deal",
    "DealEvent",
    "Order",
    "OrderEvent",
    "Product",
    "ProductionRecord",
    "SupportInteraction",
    "Decision",
    "DecisionHistory",
    "Task",
]

# Register additive v2 tables with Alembic metadata.
from app.models import impact as impact  # noqa: E402
