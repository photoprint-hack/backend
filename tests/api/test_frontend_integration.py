from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.models import Alert, CapacityPlan, Decision, Department, Order, Product, Task, User


async def login(client, role):
    response = await client.post(
        "/api/v1/auth/login", json={"email": role + "@fotoprint.demo", "password": "SeedPassword123!"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


async def test_frontend_labels_capacity_and_explicit_alert_links(client, database, seeded):
    records = (await client.get("/api/v1/production/records", headers=seeded)).json()["items"]
    assert records
    async with database() as db:
        for record in records:
            assert record["product_name"] == (await db.get(Product, record["product_id"])).name
            assert record["department_name"] == (await db.get(Department, record["department_id"])).name
            capacity = await db.scalar(
                select(CapacityPlan).where(
                    CapacityPlan.plan_date == date.fromisoformat(record["production_date"]),
                    CapacityPlan.department_id == record["department_id"],
                    CapacityPlan.product_id == record["product_id"],
                )
            )
            assert record["planned_capacity"] == (float(capacity.available_hours) if capacity else None)
        alert = await db.scalar(select(Alert).where(Alert.department_id.is_not(None)))
        director = await db.scalar(select(User).where(User.role == "director"))
        order = await db.scalar(select(Order).where(Order.department_id == alert.department_id))
        decision = Decision(
            title="Recorded explanation",
            problem="Problem",
            impact="Impact",
            cause="An observed explanation, not verified causality",
            action="Review",
            department_id=alert.department_id,
            owner_id=director.id,
            created_by=director.id,
            alert_id=alert.id,
            deadline=datetime.now(UTC) + timedelta(days=2),
            priority="high",
            expected_result="Verified result",
        )
        db.add(decision)
        task = Task(
            title="Explicit order link",
            department_id=alert.department_id,
            assignee_id=director.id,
            created_by=director.id,
            alert_id=alert.id,
            order_id=order.id,
            deadline=datetime.now(UTC) + timedelta(days=2),
            priority="high",
        )
        db.add(task)
        await db.commit()
        alert_id, task_id, decision_id, order_id = map(str, [alert.id, task.id, decision.id, order.id])
    response = await client.get("/api/v1/alerts/" + alert_id, headers=seeded)
    assert response.status_code == 200, response.text
    card = response.json()["data"]
    assert card["alert"]["department_name"]
    assert card["alert"]["metric_name"]
    assert {"text": decision.cause, "confirmed": False} in card["causes"]
    assert order_id in {row["id"] for row in card["related_orders"]}
    for path in ["/tasks/" + task_id, "/decisions/" + decision_id]:
        item = (await client.get("/api/v1" + path, headers=seeded)).json()["data"]
        assert item["alert_title"] == card["alert"]["title"]


async def test_mine_product_filter_and_minsk_deadline(client, database, seeded):
    async with database() as db:
        director = await db.scalar(select(User).where(User.role == "director"))
        employee = await db.scalar(select(User).where(User.role == "employee"))
        order = await db.scalar(select(Order).where(Order.department_id == employee.department_id))
        decision = Decision(
            title="Product-specific decision",
            problem="Problem",
            impact="Impact",
            cause="Recorded cause",
            action="Review",
            department_id=employee.department_id,
            owner_id=director.id,
            created_by=director.id,
            deadline=datetime.now(UTC) + timedelta(days=2),
            priority="medium",
            expected_result="Result",
        )
        db.add(decision)
        await db.flush()
        db.add(
            Task(
                title="Director own task",
                department_id=employee.department_id,
                assignee_id=director.id,
                created_by=director.id,
                decision_id=decision.id,
                order_id=order.id,
                deadline=datetime.now(UTC) + timedelta(days=2),
                priority="medium",
            )
        )
        await db.commit()
        product_id, decision_id, director_id = map(str, [order.product_id, decision.id, director.id])
    mine = await client.get("/api/v1/tasks?mine=true", headers=seeded)
    assert mine.status_code == 200, mine.text
    assert mine.json()["items"]
    assert all(item["assignee_id"] == director_id for item in mine.json()["items"])
    included = await client.get("/api/v1/decisions", params={"product_id": product_id}, headers=seeded)
    assert included.status_code == 200, included.text
    assert decision_id in {item["id"] for item in included.json()["items"]}
    excluded = await client.get("/api/v1/decisions", params={"product_id": str(uuid4())}, headers=seeded)
    assert excluded.status_code == 200 and excluded.json()["total"] == 0
    day = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    payload = {
        "title": "End of Minsk day",
        "assignee_id": str(employee.id),
        "department_id": str(employee.department_id),
        "deadline": day + "T23:59:59.999+03:00",
        "priority": "medium",
    }
    created = await client.post(
        "/api/v1/tasks", headers={**seeded, "Idempotency-Key": str(uuid4())}, json=payload
    )
    assert created.status_code == 201, created.text
    assert (
        datetime.fromisoformat(created.json()["data"]["deadline"]).astimezone(UTC).isoformat()
        == day + "T20:59:59.999000+00:00"
    )
    employee_headers = await login(client, "employee")
    changed = await client.patch(
        "/api/v1/tasks/" + created.json()["data"]["id"],
        headers=employee_headers,
        json={"version": 1, "status": "in_progress"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["alert_title"] is None


async def test_alert_context_never_discloses_foreign_order(client, database, seeded):
    headers = await login(client, "manager")
    async with database() as db:
        manager = await db.scalar(select(User).where(User.email == "manager@fotoprint.demo"))
        alert = await db.scalar(select(Alert).where(Alert.department_id == manager.department_id))
        foreign = await db.scalar(select(Order).where(Order.department_id != manager.department_id))
        # Deliberately inconsistent imported link: both layers must still enforce scope.
        db.add(
            Task(
                title="Untrusted historical link",
                alert_id=alert.id,
                order_id=foreign.id,
                department_id=manager.department_id,
                assignee_id=manager.id,
                created_by=manager.id,
                deadline=datetime.now(UTC) + timedelta(days=2),
                priority="low",
            )
        )
        await db.commit()
    response = await client.get("/api/v1/alerts/" + str(alert.id), headers=headers)
    assert response.status_code == 200, response.text
    assert str(foreign.id) not in {row["id"] for row in response.json()["data"]["related_orders"]}
