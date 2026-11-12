import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.models import Task


async def test_concurrent_idempotent_posts_and_version_conflicts(client, database, seeded):
    from app.models import Department, User

    async with database() as db:
        department = await db.scalar(select(Department.id).where(Department.code == "sales"))
        employee = await db.scalar(select(User.id).where(User.role == "employee"))
    headers = {**seeded, "Idempotency-Key": str(uuid4())}
    payload = {
        "title": "Concurrent task",
        "assignee_id": str(employee),
        "department_id": str(department),
        "deadline": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "priority": "high",
    }
    responses = await asyncio.gather(
        *[client.post("/api/v1/tasks", headers=headers, json=payload) for _ in range(4)]
    )
    assert all(response.status_code == 201 for response in responses), [r.text for r in responses]
    identifiers = {r.json()["data"]["id"] for r in responses}
    assert len(identifiers) == 1
    async with database() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Task).where(Task.title == "Concurrent task"))
            == 1
        )
    path = "/api/v1/tasks/" + next(iter(identifiers))
    changes = await asyncio.gather(
        client.patch(path, headers=seeded, json={"version": 1, "status": "in_progress"}),
        client.patch(path, headers=seeded, json={"version": 1, "description": "Other change"}),
    )
    assert sorted(r.status_code for r in changes) == [200, 409]
