from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import (
    Alert,
    Customer,
    Decision,
    Metric,
    Order,
    ProductionRecord,
    SupportInteraction,
    Task,
    User,
)
from app.seed.service import seed


@pytest.fixture
async def seeded(database, client):
    passwords = {role: "SeedPassword123!" for role in ["admin", "director", "manager", "analyst", "employee"]}
    async with database() as db:
        await seed(db, passwords=passwords)
        await db.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": "director@fotoprint.demo", "password": "SeedPassword123!"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


async def test_seed_kpis_and_dashboard_filters(client, database, seeded):
    response = await client.get("/api/v1/dashboard", headers=seeded)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    kpis = {x["code"]: x for x in data["kpis"]}
    assert len(kpis) == 12
    assert kpis["revenue"]["actual"] > 0
    assert kpis["gross_margin"]["actual"] == 22
    assert kpis["staffing_coverage"]["actual"] == 75
    assert kpis["revenue"]["status"] == "critical"
    assert data["critical_alerts_count"] >= 2
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Order)) == 500
        assert await db.scalar(select(func.count()).select_from(Customer)) == 200
        assert await db.scalar(select(func.count()).select_from(SupportInteraction)) == 300
        assert await db.scalar(select(func.count()).select_from(ProductionRecord)) >= 100
        assert await db.scalar(select(func.count()).select_from(Metric)) == 12
        first = await db.scalar(select(Order))
    filtered = await client.get("/api/v1/dashboard?product_id=" + str(first.product_id), headers=seeded)
    assert filtered.status_code == 200, filtered.text
    subset = {x["code"]: x for x in filtered.json()["data"]["kpis"]}
    assert subset["revenue"]["actual"] < kpis["revenue"]["actual"]
    assert subset["staffing_coverage"]["actual"] == kpis["staffing_coverage"]["actual"]
    assert subset["staffing_coverage"]["context"]["ignored_filters"] == ["product_id"]
    breakdown = await client.get("/api/v1/metrics/revenue/breakdown?group_by=order", headers=seeded)
    assert breakdown.status_code == 200, breakdown.text
    assert breakdown.json()["items"][0]["links"][0]["object_type"] == "order"


async def test_reseed_does_not_duplicate_or_overwrite_work(client, database, seeded):
    async with database() as db:
        before = {
            model: await db.scalar(select(func.count()).select_from(model))
            for model in [Order, Alert, Decision, Task]
        }
        task = await db.scalar(select(Task))
        task.status = "in_progress"
        task.version = 2
        user = await db.scalar(select(User).where(User.role == "employee"))
        old = user.password_hash
        await db.commit()
        await seed(
            db,
            passwords={
                role: "ChangedPassword123!"
                for role in ["admin", "director", "manager", "analyst", "employee"]
            },
        )
        await db.commit()
        for model, count in before.items():
            assert await db.scalar(select(func.count()).select_from(model)) == count
        await db.refresh(task)
        await db.refresh(user)
        assert task.status == "in_progress"
        assert user.password_hash == old


async def test_manager_analytics_is_scoped_and_alert_does_not_reopen(client, database, seeded):
    admin = await client.post(
        "/api/v1/auth/login", json={"email": "admin@fotoprint.demo", "password": "SeedPassword123!"}
    )
    admin_headers = {"Authorization": "Bearer " + admin.json()["data"]["access_token"]}
    alert = (await client.get("/api/v1/alerts", headers=seeded)).json()["items"][0]
    closed = await client.patch(
        "/api/v1/alerts/" + alert["id"], headers=seeded, json={"status": "resolved", "comment": "Проверено"}
    )
    assert closed.status_code == 200, closed.text
    recalculated = await client.post("/api/v1/metrics/recalculate", headers=admin_headers, json={})
    assert recalculated.status_code == 200, recalculated.text
    assert (await client.get("/api/v1/alerts/" + alert["id"], headers=seeded)).json()["data"]["alert"][
        "status"
    ] == "resolved"
    manager = await client.post(
        "/api/v1/auth/login", json={"email": "manager@fotoprint.demo", "password": "SeedPassword123!"}
    )
    manager_headers = {"Authorization": "Bearer " + manager.json()["data"]["access_token"]}
    own = (await client.get("/api/v1/dashboard", headers=manager_headers)).json()["data"]
    assert own["filters"]["department_id"] is not None
    denied = await client.get("/api/v1/dashboard?department_id=" + str(uuid4()), headers=manager_headers)
    assert denied.status_code == 403
