"""The retired views disappear reversibly without changing business data."""

import importlib.util

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text


async def test_view_removal_preserves_seeded_tables(database, seeded_database, project_root):
    spec = importlib.util.spec_from_file_location(
        "test_remove_metabase", project_root / "alembic/versions/20261112_06_remove_metabase.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = database.kw["bind"]

    async def snapshot(connection):
        tables = (
            (
                await connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename"
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            table: (await connection.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t ORDER BY id')))
            .scalars()
            .all()
            for table in tables
        }

    async def views(connection):
        return set(
            (
                await connection.execute(
                    text("SELECT viewname FROM pg_views WHERE schemaname = current_schema()")
                )
            )
            .scalars()
            .all()
        )

    def run(connection, operation):
        with Operations.context(MigrationContext.configure(connection)):
            operation()

    async with engine.begin() as connection:
        before = await snapshot(connection)
        assert not await views(connection)
        await connection.run_sync(run, migration.downgrade)
        assert await views(connection) == {
            "v_dashboard_kpi",
            "v_revenue_by_day",
            "v_orders_by_status",
            "v_sales_plan_fact",
            "v_production_quality",
            "v_support_sla",
            "v_staffing_coverage",
            "v_capacity_forecast",
        }
        for view in await views(connection):
            await connection.execute(text(f'SELECT * FROM "{view}" LIMIT 1'))
        await connection.run_sync(run, migration.upgrade)
        assert not await views(connection)
        assert await snapshot(connection) == before
