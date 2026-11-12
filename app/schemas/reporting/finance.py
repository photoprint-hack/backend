from datetime import datetime
from typing import Literal

from app.schemas.analytics.metrics import Context
from app.schemas.common import Schema


class PlanFact(Schema):
    plan: float | None
    fact: float | None
    deviation: float | None
    achievement_percent: float | None


class BDR(Schema):
    revenue: PlanFact
    direct_cost: PlanFact
    operating_cost: PlanFact
    profit: PlanFact


class BDDS(Schema):
    inflow: PlanFact
    outflow: PlanFact
    net: PlanFact


class FinanceSummary(Schema):
    context: Context
    currency: Literal["BYN"]
    revenue: float | None
    direct_cost: float | None
    operating_cost: float | None
    gross_profit: float | None
    gross_margin_percent: float | None
    bdr: BDR
    bdds: BDDS
    bdr_context: Context
    bdds_context: Context
    notices: list[str]
    updated_at: datetime | None
