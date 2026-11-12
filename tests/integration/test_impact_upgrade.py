"""Exercise additive upgrade with actual v1.2 data present, and reversible DDL."""

import importlib.util

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select

from app.models import Decision, Department, Order, Task, User
from app.models.impact import ManagementAction
from app.seed.context import create_context
from app.seed.stages.catalog import seed_catalog
from app.seed.stages.orders import seed_orders
from app.seed.stages.plans import seed_plans
from app.seed.stages.sources import seed_sources
from app.seed.stages.support import seed_support
from app.seed.stages.workflow import seed_workflow
from app.services.serialization import columns


def revisions(project_root):
    result = []
    for number in ["03", "04", "05"]:
        spec = importlib.util.spec_from_file_location(
            "test_upgrade_" + number,
            project_root / f"alembic/versions/20261112_{number}_impact.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result.append(module)
    return result


async def test_additive_upgrade_preserves_existing_rows_and_passwords(database, project_root):
    engine = database.kw["bind"]
    modules = revisions(project_root)

    def down(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for module in reversed(modules):
                module.downgrade()

    async with engine.begin() as connection:
        await connection.run_sync(down)
    models = [User, Department, Order, Decision, Task]
    async with database() as db:
        ctx = await create_context(
            db,
            passwords=dict.fromkeys(
                ["admin", "director", "manager", "analyst", "employee"], "MigrationTest123!"
            ),
        )
        for stage in [seed_catalog, seed_orders, seed_support, seed_plans, seed_sources, seed_workflow]:
            await stage(ctx)
        await db.commit()
        before = {
            m: {str(row.id): columns(row) for row in (await db.scalars(select(m))).all()} for m in models
        }

    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            for module in modules:
                module.upgrade()

    async with engine.begin() as connection:
        await connection.run_sync(upgrade)
    async with database() as db:
        after = {
            m: {str(row.id): columns(row) for row in (await db.scalars(select(m))).all()} for m in models
        }
        assert before == after
        assert (await db.scalars(select(ManagementAction))).all() == []
