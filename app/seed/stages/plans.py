from datetime import timedelta
from decimal import Decimal

from app.models import (
    CapacityPlan,
    FinanceRecord,
    HRSnapshot,
    Metric,
    MetricTarget,
)
from app.seed.context import SeedContext
from app.services.analytics import DEFINITIONS, metric_id


async def seed_plans(ctx: SeedContext):
    db = ctx.db
    departments = ctx.departments
    known = ctx.known
    products = ctx.products
    reference = ctx.reference
    add = ctx.add
    # Metrics must be flushed before their daily targets (same transaction, FK ordering).
    for code, name, unit, sources, direction, category, target, formula in DEFINITIONS:
        if metric_id(code) not in known[Metric]:
            db.add(
                Metric(
                    id=metric_id(code),
                    code=code,
                    name=name,
                    description=name,
                    unit=unit,
                    formula=formula,
                    source_description=sources,
                    target_value=target,
                    direction=direction,
                    category=category,
                    is_active=True,
                )
            )
            known[Metric].add(metric_id(code))
    await db.flush()

    start = reference - timedelta(days=90)
    end = reference + timedelta(days=35)
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        for di, dept in enumerate(departments):
            for pi, product in enumerate(products):
                add(
                    CapacityPlan,
                    f"capacity:{day}:{di}:{pi}",
                    plan_date=day,
                    department_id=dept,
                    product_id=product,
                    available_hours=(
                        Decimal("0.1")
                        if day >= reference - timedelta(days=reference.weekday()) + timedelta(weeks=1)
                        and (
                            day - (reference - timedelta(days=reference.weekday()) + timedelta(weeks=1))
                        ).days
                        < 7
                        else Decimal("8")
                    )
                    if day > reference
                    else (Decimal("0.5") if offset % 14 < 7 else Decimal("8")),
                )
        if day <= reference:
            for di, dept in enumerate(departments):
                for pi, product in enumerate(products):
                    for code, value in [
                        ("revenue", Decimal(500)),
                        ("new_customers", Decimal(1)),
                        ("active_customers", Decimal(2)),
                    ]:
                        add(
                            MetricTarget,
                            f"target:{code}:{day}:{di}:{pi}",
                            metric_id=metric_id(code),
                            plan_date=day,
                            department_id=dept,
                            product_id=product,
                            target_value=value,
                        )
                for kind, amount in [
                    ("budget_revenue", Decimal(2500)),
                    ("budget_direct_cost", Decimal(1200)),
                    ("budget_operating_cost", Decimal(200)),
                    ("operating_cost", Decimal(180)),
                    ("cash_inflow", Decimal(1000)),
                    ("cash_outflow", Decimal(800)),
                    ("budget_cash_inflow", Decimal(1200)),
                    ("budget_cash_outflow", Decimal(900)),
                ]:
                    add(
                        FinanceRecord,
                        f"finance_daily:{day}:{di}:{kind}",
                        external_id=f"DAILY-{day}-{di}-{kind}",
                        department_id=dept,
                        record_date=day,
                        record_type=kind,
                        amount=amount,
                        currency="BYN",
                    )
        if offset % 7 == 0 and day <= reference:
            for di, dept in enumerate(departments):
                add(
                    HRSnapshot,
                    f"hr:{day}:{di}",
                    department_id=dept,
                    snapshot_date=day,
                    planned_headcount=12,
                    actual_headcount=11,
                    available_headcount=9,
                    required_headcount=12,
                    vacancies_count=1,
                    absences_count=2,
                )
