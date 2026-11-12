import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import AuditLog, Department, Task, User
from app.models.impact import AIAnalysis, ManagementAction, Notification, NotificationOutbox
from app.services.impact import notifications, provider


async def login(client, role):
    name = "production.manager" if role == "production" else role
    response = await client.post(
        "/api/v1/auth/login", json={"email": name + "@fotoprint.demo", "password": "SeedPassword123!"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


async def draft(client, database, headers, kind="task", assignee_role="employee", **extra):
    async with database() as db:
        person = await db.scalar(select(User).where(User.email == assignee_role + "@fotoprint.demo"))
    payload = dict(
        type=kind,
        department_id=str(person.department_id),
        assignee_id=str(person.id),
        title="Проверить отклонение",
        text="Синтетическое поручение",
        priority="critical",
        metric_code="on_time_orders",
        context={},
    )
    if kind == "task":
        payload["execution_due_at"] = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    response = await client.post(
        "/api/v1/management-actions",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**payload, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def command(client, action, name, headers, **extra):
    response = await client.post(
        f"/api/v1/management-actions/{action['id']}/{name}",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"version": action["version"], **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_graph_kpi_revision_scopes_and_bfs(client, database, seeded):
    one = await client.get("/api/v1/impact-map", headers=seeded)
    assert one.status_code == 200, one.text
    full = one.json()["data"]
    two = (await client.get("/api/v1/impact-map", headers=seeded)).json()["data"]
    assert full["graph_revision"] == two["graph_revision"]
    assert full["nodes"] and full["edges"]
    for n in full["nodes"]:
        assert UUID(n["id"])
    kpis = (await client.get("/api/v1/metrics", headers=seeded)).json()["items"]
    by_code = {x["code"]: x for x in kpis}
    for n in full["nodes"]:
        if n["type"] == "metric":
            code = n["entity_ref"]["id"]
            assert n["metadata"]["kpi"]["actual"] == by_code[code]["actual"]
    edge = full["edges"][0]
    response = await client.get(
        "/api/v1/impact-map/paths",
        headers=seeded,
        params={"from_node_id": edge["source"], "to_node_id": edge["target"], "depth": 1},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]["nodes"]) == 2
    manager = await login(client, "manager")
    own = (await client.get("/api/v1/impact-map", headers=manager)).json()["data"]
    async with database() as db:
        production = await db.scalar(select(Department).where(Department.code == "production"))
    assert (
        await client.get("/api/v1/impact-map", headers=manager, params={"department_id": str(production.id)})
    ).status_code == 403
    foreign = next(
        n for n in full["nodes"] if n["type"] == "department" and n["entity_ref"]["id"] == str(production.id)
    )
    assert (
        await client.get(f"/api/v1/impact-map/nodes/{foreign['id']}/neighbors", headers=manager)
    ).status_code == 404
    assert not any(n["id"] == foreign["id"] for n in own["nodes"])
    employee = await login(client, "employee")
    limited = (await client.get("/api/v1/impact-map", headers=employee)).json()["data"]
    assert not any(n["type"] in {"metric", "department", "source", "risk"} for n in limited["nodes"])


async def test_full_action_workflow_and_independent_verification(client, database, seeded):
    employee = await login(client, "employee")
    action = await draft(client, database, seeded)
    assert action["task_id"] is None
    action = await command(client, action, "send", seeded)
    assert action["task_id"] and action["response_due_at"]
    action = await command(client, action, "acknowledge", employee)
    action = await command(client, action, "start", employee)
    action = await command(client, action, "resolve", employee, result="Проверено по синтетическим данным")
    assert action["execution_status"] == "completed" and action["status"] == "resolved"
    assert (
        await client.post(
            f"/api/v1/management-actions/{action['id']}/verify",
            headers={**employee, "Idempotency-Key": str(uuid4())},
            json={"version": action["version"], "verification_note": "Сам"},
        )
    ).status_code == 403
    action = await command(
        client, action, "verify", seeded, verification_note="Результат проверен независимо"
    )
    assert action["status"] == "verified"
    history = await client.get(f"/api/v1/management-actions/{action['id']}/history", headers=employee)
    assert history.status_code == 200 and history.json()["total"] >= 7
    assert (await client.get("/api/v1/audit-logs", headers=employee)).status_code == 403


async def test_send_concurrency_replay_and_old_task_patch(client, database, seeded):
    employee = await login(client, "employee")
    action = await draft(client, database, seeded)
    key = str(uuid4())
    endpoint = f"/api/v1/management-actions/{action['id']}/send"
    headers = {**seeded, "Idempotency-Key": key}
    payload = {"version": action["version"]}
    a, b = await asyncio.gather(
        client.post(endpoint, headers=headers, json=payload),
        client.post(endpoint, headers=headers, json=payload),
    )
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json() == b.json()
    action = a.json()["data"]
    conflict = await client.post(endpoint, headers=headers, json={"version": 999})
    assert conflict.status_code == 409
    for status in ["in_progress", "completed"]:
        task = (await client.get("/api/v1/tasks/" + action["task_id"], headers=employee)).json()["data"]
        response = await client.patch(
            "/api/v1/tasks/" + action["task_id"],
            headers=employee,
            json={"version": task["version"], "status": status},
        )
        assert response.status_code == 200, response.text
    value = (await client.get("/api/v1/management-actions/" + action["id"], headers=seeded)).json()["data"]
    assert value["status"] == "resolved" and value["acknowledged_at"] is None
    async with database() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Task).where(Task.id == UUID(action["task_id"])))
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(NotificationOutbox)
                .where(
                    NotificationOutbox.action_id == UUID(action["id"]),
                    NotificationOutbox.kind == "action_sent",
                )
            )
            == 1
        )


async def test_notifications_delivery_read_and_sla_dedup(client, database, seeded):
    employee = await login(client, "employee")
    action = await draft(client, database, seeded, kind="explanation_request")
    action = await command(client, action, "send", seeded)
    await asyncio.gather(notifications.tick(database), notifications.tick(database))
    listing = await client.get("/api/v1/notifications", headers=employee)
    assert listing.status_code == 200, listing.text
    item = next(n for n in listing.json()["items"] if n["action_id"] == action["id"])
    assert item["read_at"] is None and item["delivered_at"] is None
    for endpoint in ["delivered", "read"]:
        response = await client.post(f"/api/v1/notifications/{item['id']}/{endpoint}", headers=employee)
        assert response.status_code == 200, response.text
    unchanged = (await client.get("/api/v1/management-actions/" + action["id"], headers=seeded)).json()[
        "data"
    ]
    assert unchanged["acknowledged_at"] is None
    async with database() as db:
        obj = await db.get(ManagementAction, UUID(action["id"]))
        obj.response_due_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    await notifications.tick(database)
    await notifications.tick(database)
    async with database() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(NotificationOutbox)
            .where(
                NotificationOutbox.action_id == UUID(action["id"]),
                NotificationOutbox.kind == "escalation_response",
            )
        )
        assert count == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.action_id == UUID(action["id"]),
                    Notification.recipient_id == UUID(action["assignee_id"]),
                )
            )
            == 2
        )


async def test_action_readonly_roles_and_self_verification(client, database, seeded):
    analyst = await login(client, "analyst")
    action = await draft(client, database, seeded, kind="reminder", assignee_role="manager")
    assert (
        await client.get("/api/v1/management-actions/" + action["id"], headers=analyst)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/management-actions/{action['id']}/send",
            headers={**analyst, "Idempotency-Key": str(uuid4())},
            json={"version": action["version"]},
        )
    ).status_code == 403
    manager = await login(client, "manager")
    action = await command(client, action, "send", seeded)
    action = await command(client, action, "acknowledge", manager)
    action = await command(client, action, "resolve", manager, result="Объяснение")
    assert (
        await client.post(
            f"/api/v1/management-actions/{action['id']}/verify",
            headers={**manager, "Idempotency-Key": str(uuid4())},
            json={"version": action["version"], "verification_note": "Сам"},
        )
    ).status_code == 403
    foreign = await login(client, "production")
    assert (
        await client.get("/api/v1/management-actions/" + action["id"], headers=foreign)
    ).status_code == 404


def response_content(context):
    ref = context["nodes"][0]["id"]
    return dict(
        summary="Причина требует проверки",
        changes=[],
        verified_facts=[{"text": "Придуманная причина", "refs": [ref]}],
        calculated_dependencies=[],
        correlations=[],
        hypotheses=[{"text": "Нужно проверить загрузку", "refs": [ref]}],
        possible_impacts=[],
        recommendations=[],
        data_gaps=[],
        suggested_responsible=None,
        draft_text="Проверьте отклонение",
    )


async def test_ai_cache_stale_scope_and_server_evidence(client, database, seeded, monkeypatch):
    config = get_settings()
    monkeypatch.setattr(config, "openrouter_api_key", SecretStr("fake-test-key"))
    seen = []

    async def fake(context):
        seen.append(context)
        return response_content(context), "test/free"

    monkeypatch.setattr(provider, "generate", fake)
    graph = (await client.get("/api/v1/impact-map", headers=seeded)).json()["data"]
    payload = dict(
        request_key=str(uuid4()),
        metric_code="on_time_orders",
        context={},
        graph_revision=graph["graph_revision"],
    )
    first = await client.post("/api/v1/impact-map/analyze", headers=seeded, json=payload)
    assert first.status_code == 200, first.text
    result = first.json()["data"]
    assert not result["cached"] and "Придуманная" not in str(result["analysis"]["verified_facts"])
    replay = await client.post(
        "/api/v1/impact-map/analyze", headers=seeded, json={**payload, "request_key": str(uuid4())}
    )
    assert replay.status_code == 200 and replay.json()["data"]["cached"] and len(seen) == 1
    assert "password" not in str(seen).lower() and "email" not in str(seen).lower()
    stale = await client.post(
        "/api/v1/impact-map/analyze",
        headers=seeded,
        json={**payload, "request_key": str(uuid4()), "graph_revision": "outdated"},
    )
    assert stale.status_code == 409
    employee = await login(client, "employee")
    assert (
        await client.post("/api/v1/impact-map/analyze", headers=employee, json=payload)
    ).status_code == 403


async def test_ai_missing_key_and_bad_reference(client, database, seeded, monkeypatch):
    config = get_settings()
    monkeypatch.setattr(config, "openrouter_api_key", None)
    graph = (await client.get("/api/v1/impact-map", headers=seeded)).json()["data"]
    payload = dict(
        request_key=str(uuid4()),
        metric_code="on_time_orders",
        context={},
        graph_revision=graph["graph_revision"],
    )
    assert (await client.post("/api/v1/impact-map/analyze", headers=seeded, json=payload)).status_code == 503
    monkeypatch.setattr(config, "openrouter_api_key", SecretStr("fake-test-key"))

    async def fake(context):
        value = response_content(context)
        value["hypotheses"][0]["refs"] = [str(uuid4())]
        return value, "test/free"

    monkeypatch.setattr(provider, "generate", fake)
    bad = await client.post("/api/v1/impact-map/analyze", headers=seeded, json=payload)
    assert bad.status_code == 503, bad.text
    async with database() as db:
        row = await db.scalar(select(AIAnalysis))
        assert row.status == "failed"


async def test_mary_partial_replay_and_scope(client, database, seeded):
    admin = await login(client, "admin")
    async with database() as db:
        department = await db.scalar(select(Department).where(Department.code == "sales"))
    record = dict(
        external_id="test-mary",
        event_type="lead_qualified",
        occurred_at=datetime.now(UTC).isoformat(),
        department_id=str(department.id),
        channel="demo",
    )
    body = {"records": [record, {**record, "external_id": "invalid", "department_id": str(uuid4())}]}
    result = await client.post("/api/v1/integrations/mary/events", headers=admin, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["inserted"] == result.json()["data"]["failed"] == 1
    replay = await client.post("/api/v1/integrations/mary/events", headers=admin, json={"records": [record]})
    assert replay.json()["data"]["skipped"] == 1
    assert (
        await client.post("/api/v1/integrations/mary/events", headers=seeded, json=body)
    ).status_code == 403


async def test_ai_concurrent_requests_share_provider_and_retry_key(client, database, seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", SecretStr("fake-test-key"))
    calls = []

    async def fake(context):
        calls.append(context)
        await asyncio.sleep(0.4)
        return response_content(context), "test/free"

    monkeypatch.setattr(provider, "generate", fake)
    graph = (await client.get("/api/v1/impact-map", headers=seeded)).json()["data"]
    payload = dict(
        request_key=str(uuid4()),
        metric_code="on_time_orders",
        context={},
        graph_revision=graph["graph_revision"],
    )
    a, b = await asyncio.gather(
        *[client.post("/api/v1/impact-map/analyze", headers=seeded, json=payload) for _ in range(2)]
    )
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert a.json()["data"]["id"] == b.json()["data"]["id"] and len(calls) == 1
    conflict = await client.post(
        "/api/v1/impact-map/analyze", headers=seeded, json={**payload, "metric_code": "revenue"}
    )
    assert conflict.status_code == 409


async def test_ai_role_change_in_flight_never_returns_old_cache(client, database, seeded, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", SecretStr("fake-test-key"))

    async def fake(context):
        async with database() as db:
            director = await db.scalar(select(User).where(User.role == "director"))
            department_id = await db.scalar(select(Department.id).where(Department.code == "sales"))
            director.role, director.department_id = "employee", department_id
            await db.commit()
        return response_content(context), "test/free"

    monkeypatch.setattr(provider, "generate", fake)
    graph = (await client.get("/api/v1/impact-map", headers=seeded)).json()["data"]
    payload = dict(
        request_key=str(uuid4()),
        metric_code="on_time_orders",
        context={},
        graph_revision=graph["graph_revision"],
    )
    result = await client.post("/api/v1/impact-map/analyze", headers=seeded, json=payload)
    assert result.status_code == 403, result.text


async def test_reassign_deadline_request_and_terminal_task_independence(client, database, seeded):
    employee = await login(client, "employee")
    action = await draft(client, database, seeded)
    action = await command(client, action, "send", seeded)
    deadline = action["execution_due_at"]
    action = await command(
        client,
        action,
        "request-change",
        employee,
        reason="Нужен новый срок",
        execution_due_at=(datetime.now(UTC) + timedelta(days=4)).isoformat(),
    )
    assert action["execution_due_at"] == deadline
    action = await command(
        client,
        action,
        "change-deadline",
        seeded,
        reason="Согласовано",
        execution_due_at=(datetime.now(UTC) + timedelta(days=4)).isoformat(),
    )
    async with database() as db:
        manager = await db.scalar(select(User).where(User.email == "manager@fotoprint.demo"))
        manager_id = str(manager.id)
    action = await command(
        client, action, "reassign", seeded, reason="Передача руководителю", assignee_id=manager_id
    )
    assert (
        action["assignee_id"] == manager_id
        and action["assignment_cycle"] == 2
        and action["acknowledged_at"] is None
    )
    assert (
        await client.get("/api/v1/management-actions/" + action["id"], headers=employee)
    ).status_code == 404
    action = await command(client, action, "cancel", seeded, reason="Отмена коммуникации")
    task = (await client.get("/api/v1/tasks/" + action["task_id"], headers=seeded)).json()["data"]
    assert task["status"] == "new" and action["status"] == "cancelled"


async def test_responsibility_versions_cors_and_missing_recipient(client, database, seeded):
    async with database() as db:
        department = await db.scalar(select(Department).where(Department.code == "sales"))
        head = await db.scalar(select(User).where(User.email == "manager@fotoprint.demo"))
        director = await db.scalar(select(User).where(User.email == "director@fotoprint.demo"))
    endpoint = f"/api/v1/responsibilities/departments/{department.id}"
    prior = (await client.get(endpoint, headers=seeded)).json()["data"]
    payload = {"head_id": str(head.id), "director_id": str(director.id), "version": prior["version"]}
    response = await client.put(endpoint, headers=seeded, json=payload)
    assert response.status_code == 200, response.text
    assert (await client.put(endpoint, headers=seeded, json=payload)).status_code == 409
    preflight = await client.options(
        endpoint, headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"}
    )
    assert preflight.status_code == 200
    action = await draft(client, database, seeded, kind="reminder")
    response = await client.patch(
        "/api/v1/management-actions/" + action["id"],
        headers=seeded,
        json={"version": action["version"], "assignee_id": None},
    )
    action = response.json()["data"]
    response = await client.post(
        f"/api/v1/management-actions/{action['id']}/send",
        headers={**seeded, "Idempotency-Key": str(uuid4())},
        json={"version": action["version"]},
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "RESPONSIBLE_NOT_CONFIGURED"


async def test_company_snapshot_is_replaced_by_department_snapshot_for_manager(client, database, seeded):
    manager = await login(client, "manager")
    action = await draft(
        client, database, seeded, kind="reminder", assignee_role="manager", metric_code="revenue"
    )
    assert action["context"]["department_id"] is None
    company_actual = action["context"]["problem"]["actual"]
    visible = await client.get("/api/v1/management-actions/" + action["id"], headers=manager)
    assert visible.status_code == 200, visible.text
    snapshot = visible.json()["data"]["context"]
    assert snapshot["department_id"] == action["department_id"]
    own = await client.get("/api/v1/metrics/revenue", headers=manager)
    assert snapshot["problem"]["actual"] == own.json()["data"]["actual"]
    assert company_actual > snapshot["problem"]["actual"]
    assert "scoped_context" not in visible.json()["data"]
    # Later dashboard requests cannot rewrite either persisted snapshot.
    await client.get("/api/v1/dashboard", headers=seeded, params={"department_id": action["department_id"]})
    reread = (await client.get("/api/v1/management-actions/" + action["id"], headers=seeded)).json()["data"]
    assert reread["context"] == action["context"]


async def test_action_audit_edits_and_replay_after_role_loss(client, database, seeded):
    async with database() as db:
        manager = await db.scalar(select(User).where(User.email == "manager@fotoprint.demo"))
        dept = str(manager.department_id)
        manager_id = str(manager.id)
    key = str(uuid4())
    payload = dict(
        type="reminder",
        department_id=dept,
        assignee_id=manager_id,
        title="Исходный текст",
        text="Синтетический контекст",
        priority="medium",
        metric_code="revenue",
        context={},
    )
    headers = {**seeded, "Idempotency-Key": key}
    response = await client.post("/api/v1/management-actions", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    action = response.json()["data"]
    response = await client.patch(
        "/api/v1/management-actions/" + action["id"],
        headers=seeded,
        json={"version": action["version"], "title": "Изменённый текст"},
    )
    assert response.status_code == 200, response.text
    async with database() as db:
        event = await db.scalar(
            select(AuditLog).where(
                AuditLog.object_id == UUID(action["id"]), AuditLog.action == "management_action.edited"
            )
        )
        assert (
            event.old_values["title"] == "Исходный текст" and event.new_values["title"] == "Изменённый текст"
        )
        director = await db.scalar(select(User).where(User.email == "director@fotoprint.demo"))
        director.role, director.department_id = "manager", UUID(dept)
        await db.commit()
    protected = await client.post("/api/v1/management-actions", headers=headers, json=payload)
    assert protected.status_code == 403, protected.text
    current = await client.get("/api/v1/management-actions/" + action["id"], headers=seeded)
    assert current.status_code == 200 and current.json()["data"]["context"]["department_id"] == dept
