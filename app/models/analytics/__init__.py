"""Compatibility exports; definitions live in domain modules."""

from app.models.analytics.alerts import Alert
from app.models.analytics.forecast import ForecastRecord
from app.models.analytics.metrics import Metric, MetricTarget, MetricValue
from app.models.reporting.finance import FINANCE_TYPES, FinanceRecord
from app.models.reporting.hr import HRSnapshot

__all__ = [
    "Alert",
    "FINANCE_TYPES",
    "FinanceRecord",
    "ForecastRecord",
    "HRSnapshot",
    "Metric",
    "MetricTarget",
    "MetricValue",
]
