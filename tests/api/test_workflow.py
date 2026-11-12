from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import hash_password
from app.models import AuditLog, Customer, Decision, DecisionHistory, Department, Product, User


@pytest.fixture
async def setup_work(database, client):
    async with database() as db:
        dept = Department(code="work", name="Work")
        other = Department(code="other", name="Other")
        db.add_all([dept, other])
        await db.flush()
        people = {}
        for role in ["admin", "director", "manager", "employee", "analyst"]:
            person = User(
                email=role + "@example.com",
                full_name=role,
                role=role,
                department_id=dept.id,
                password_hash=hash_password("WorkPassword123!"),
            )
            people[role] = person
            db.add(person)
        product = Product(
            code="photo",
            name="Photo",
            category="photo",
            standard_price=Decimal("10"),
            standard_hours_per_unit=Decimal("0.1"),
            currency="BYN",
            is_active=True,
        )
        customer = Customer(
            name="Customer", customer_type="b2c", segment="retail", acquisition_channel="website"
        )
        db.add_all([product, customer])
        await db.commit()

    async def headers(role):
        response = await client.post(
            "/api/v1/auth/login", json={"email": people[role].email, "password": "WorkPassword123!"}
        )
        assert response.status_code == 200, response.text
        return {
            "Authorization": "Bearer " + response.json()["data"]["access_token"],
            "Idempotency-Key": str(uuid4()),
        }

    return people, dept, other, product, customer, headers


async def test_decision_task_verification_history_and_idempotency(client, database, setup_work):
    people, dept, _other, _product, _customer, headers = setup_work
    director = await headers("director")
    payload = {
        "title": "Fix issue",
        "problem": "Problem",
        "impact": "Impact",
        "cause": "Needs investigation",
        "action": "Investigate",
        "department_id": str(dept.id),
        "owner_id": str(people["manager"].id),
        "deadline": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "priority": "high",
        "expected_result": "Issue explained",
    }
    created = await client.post("/api/v1/decisions", headers=director, json=payload)
    assert created.status_code == 201, created.text
    decision = created.json()["data"]
    replay = await client.post("/api/v1/decisions", headers=director, json=payload)
    assert replay.status_code == 201
    assert replay.json() == created.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    conflict = await client.post("/api/v1/decisions", headers=director, json={**payload, "title": "Other"})
    assert conflict.status_code == 409
    task = await client.post(
        "/api/v1/tasks",
        headers={**director, "Idempotency-Key": str(uuid4())},
        json={
            "title": "Investigate",
            "department_id": str(dept.id),
            "assignee_id": str(people["employee"].id),
            "deadline": payload["deadline"],
            "priority": "high",
            "decision_id": decision["id"],
        },
    )
    assert task.status_code == 201, task.text
    task = task.json()["data"]
    employee = await headers("employee")
    assert (await client.get("/api/v1/decisions/" + decision["id"], headers=employee)).status_code == 200
    assert (
        await client.get("/api/v1/decisions/" + decision["id"] + "/history", headers=employee)
    ).status_code == 403
    forbidden = await client.patch(
        "/api/v1/tasks/" + task["id"], headers=employee, json={"version": 1, "description": "cannot change"}
    )
    assert forbidden.status_code == 403
    start = await client.patch(
        "/api/v1/tasks/" + task["id"], headers=employee, json={"version": 1, "status": "in_progress"}
    )
    assert start.status_code == 200, start.text
    done = await client.patch(
        "/api/v1/tasks/" + task["id"], headers=employee, json={"version": 2, "status": "completed"}
    )
    assert done.status_code == 200, done.text
    unchanged = await client.get("/api/v1/decisions/" + decision["id"], headers=director)
    assert unchanged.json()["data"]["status"] == "new"
    path = "/api/v1/decisions/" + decision["id"]
    start = await client.patch(path, headers=director, json={"version": 1, "status": "in_progress"})
    assert start.status_code == 200, start.text
    bad = await client.patch(path, headers=director, json={"version": 2, "status": "needs_review"})
    assert bad.status_code == 422
    stale = await client.patch(
        path, headers=director, json={"version": 1, "status": "needs_review", "actual_result": "Found cause"}
    )
    assert stale.status_code == 409
    review = await client.patch(
        path,
        headers=director,
        json={"version": 2, "status": "needs_review", "actual_result": "Cause confirmed"},
    )
    assert review.status_code == 200, review.text
    completed = await client.patch(
        path,
        headers=director,
        json={"version": 3, "status": "completed", "verification_note": "Checked source records"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["completed_at"]
    history = await client.get(path + "/history", headers=director)
    assert history.status_code == 200
    assert history.json()["total"] == 4
    async with database() as db:
        assert await db.scalar(select(func.count()).select_from(Decision)) == 1
        assert await db.scalar(select(func.count()).select_from(DecisionHistory)) == 4
        assert (
            await db.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == "decision.created")
            )
            == 1
        )


async def test_order_creation_and_employee_explicit_link(client, database, setup_work):
    people, dept, other, product, customer, headers = setup_work
    director = await headers("director")
    body = {
        "customer_id": str(customer.id),
        "product_id": str(product.id),
        "department_id": str(dept.id),
        "quantity": 10,
        "amount": 100,
        "currency": "BYN",
        "channel": "website",
        "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    }
    response = await client.post("/api/v1/orders", headers=director, json=body)
    assert response.status_code == 201, response.text
    order = response.json()["data"]
    assert order["amount"] == 100
    assert order["standard_hours_per_unit"] == 0.1
    employee = await headers("employee")
    assert (await client.get("/api/v1/orders/" + order["id"], headers=employee)).status_code == 404
    task = await client.post(
        "/api/v1/tasks",
        headers={**director, "Idempotency-Key": str(uuid4())},
        json={
            "title": "Order task",
            "department_id": str(dept.id),
            "assignee_id": str(people["employee"].id),
            "deadline": body["due_at"],
            "priority": "medium",
            "order_id": order["id"],
        },
    )
    assert task.status_code == 201, task.text
    assert (await client.get("/api/v1/orders/" + order["id"], headers=employee)).status_code == 200
    assert (await client.get("/api/v1/orders", headers=employee)).json()["total"] == 1
    manager = await headers("manager")
    foreign = await client.get("/api/v1/orders?department_id=" + str(other.id), headers=manager)
    assert foreign.status_code == 403


async def test_analyst_cannot_create_and_missing_key_rejected(client, database, setup_work):
    people, dept, _other, _product, _customer, headers = setup_work
    payload = {
        "title": "Task",
        "assignee_id": str(people["employee"].id),
        "department_id": str(dept.id),
        "deadline": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "priority": "low",
    }
    analyst = await headers("analyst")
    assert (await client.post("/api/v1/tasks", headers=analyst, json=payload)).status_code == 403
    director = await headers("director")
    director.pop("Idempotency-Key")
    assert (await client.post("/api/v1/tasks", headers=director, json=payload)).status_code == 400
