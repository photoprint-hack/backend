import re
from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError


async def test_bi_native_questions_respect_manager_scope_and_match_api(client, database, seeded):
    manager = await client.post(
        "/api/v1/auth/login", json={"email": "manager@fotoprint.demo", "password": "SeedPassword123!"}
    )
    headers = {"Authorization": "Bearer " + manager.json()["data"]["access_token"]}
    dashboard = (await client.get("/api/v1/dashboard", headers=headers)).json()["data"]
    params = {
        "date_from": date.fromisoformat(dashboard["period"]["date_from"]),
        "date_to": date.fromisoformat(dashboard["period"]["date_to"]),
        "department_id": dashboard["filters"]["department_id"],
        "product_id": "all",
    }
    raw = (Path(__file__).parents[1] / "bi/questions.sql").read_text()
    queries = [part.strip() for part in re.sub(r"--[^\n]*", "", raw).split(";") if part.strip()]
    async with database() as db:
        results = []
        for query in queries:
            sql = re.sub(r"\{\{(\w+)\}\}", r":\1", query)
            results.append((await db.execute(text(sql), params)).mappings().all())
        api_revenue = next(k["actual"] for k in dashboard["kpis"] if k["code"] == "revenue")
        assert float(sum(row["revenue"] for row in results[0])) == api_revenue
        assert float(results[4][0]["staffing_coverage"]) == 75
        company = (
            (
                await db.execute(
                    text(re.sub(r"\{\{(\w+)\}\}", r":\1", queries[0])), {**params, "department_id": "company"}
                )
            )
            .mappings()
            .all()
        )
        assert sum(row["revenue"] for row in company) > sum(row["revenue"] for row in results[0])


async def test_readonly_bi_role_cannot_read_auth_tables(database, seeded):
    async with database() as db:
        privileged = await db.scalar(text("SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user"))
        if not privileged:
            import pytest

            pytest.skip("Temporary DB role creation is unavailable to this test account")
        role = "test_bi_" + uuid4().hex
        schema = await db.scalar(text("SELECT current_schema()"))
        script = (Path(__file__).parents[1] / "bi/setup_readonly.sql").read_text()
        script = "\n".join(
            line
            for line in script.splitlines()
            if not line.startswith("\\") and line.strip() not in {"BEGIN;", "COMMIT;"}
        )
        script = script.replace("photoprint_bi", role).replace("public", schema)
        connection = await db.connection()
        raw = await connection.get_raw_connection()
        await raw.driver_connection.execute(script)
        await db.execute(text(f'SET LOCAL ROLE "{role}"'))
        assert await db.scalar(text("SELECT count(*) FROM v_revenue_by_day")) > 0
        for table in ["users", "refresh_tokens", "audit_logs", "orders"]:
            try:
                async with db.begin_nested():
                    await db.execute(text("SELECT * FROM " + table + " LIMIT 1"))
            except ProgrammingError:
                pass
            else:
                raise AssertionError("BI role unexpectedly read " + table)
        await db.rollback()  # Also removes the temporary role and grants.
