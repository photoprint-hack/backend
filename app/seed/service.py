"""Coordinate deterministic seed stages in one caller-owned transaction."""

from datetime import date

from app.seed.context import create_context
from app.seed.context import identifier as identifier
from app.seed.stages.catalog import seed_catalog
from app.seed.stages.orders import seed_orders
from app.seed.stages.plans import seed_plans
from app.seed.stages.sources import seed_sources
from app.seed.stages.support import seed_support
from app.seed.stages.workflow import seed_workflow


async def seed(db, *, passwords: dict[str, str], reference: date | None = None, restore: bool = False):
    ctx = await create_context(db, passwords=passwords, reference=reference, restore=restore)
    await seed_catalog(ctx)
    await seed_orders(ctx)
    await seed_support(ctx)
    await seed_plans(ctx)
    await seed_sources(ctx)
    await seed_workflow(ctx)
    return {"inserted": ctx.inserted, "reference_date": ctx.reference}
