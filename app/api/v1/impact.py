from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.locks import RESPONSIBILITY
from app.core.permissions import WRITE_ROLES, department_scope, require_role
from app.models import Alert, AuditLog, Decision, Department, Order, OrderEvent, Task
from app.models.impact import ManagementAction, MaryEvent, Notification, NotificationOutbox
from app.schemas.common import Data, Page, page
from app.schemas.impact import (
    ActionCommand,
    ActionCreate,
    ActionOut,
    ActionPatch,
    ActionsQuery,
    AnalysisOut,
    Analyze,
    DepartmentAssignment,
    Graph,
    MaryBatch,
    MetricAssignment,
    NeighborsQuery,
    NotificationOut,
    NotificationsQuery,
    PathsQuery,
)
from app.schemas.shared.query import BusinessQuery, PaginationQuery
from app.services import idempotency, workflow
from app.services.impact import actions, ai, graph, mary, responsibility
from app.services.impact.snapshots import replay_allowed
from app.services.serialization import columns, serialize_many

router = APIRouter(tags=["impact"])
Key = Annotated[UUID | None, Header(alias="Idempotency-Key")]
Q = Annotated[BusinessQuery, Query()]


@router.get("/impact-map", response_model=Data[Graph])
async def impact_map(db: DB, user: CurrentUser, query: Q):
    return {"data": await graph.build(db, query, user)}


@router.get("/impact-map/paths", response_model=Data[Graph])
async def impact_paths(db: DB, user: CurrentUser, query: Annotated[PathsQuery, Query()]):
    full = await graph.build(db, query, user)
    return {
        "data": graph.explore(
            full,
            str(query.from_node_id),
            query.depth,
            query.direction,
            query.edge_types,
            str(query.to_node_id),
        )
    }


@router.get("/impact-map/nodes/{node_id}/neighbors", response_model=Data[Graph])
async def impact_neighbors(
    node_id: UUID, db: DB, user: CurrentUser, query: Annotated[NeighborsQuery, Query()]
):
    full = await graph.build(db, query, user)
    return {"data": graph.explore(full, str(node_id), query.depth, query.direction, query.edge_types)}


@router.get("/impact-map/nodes/{node_id}", response_model=Data[dict])
async def impact_node(node_id: str, db: DB, user: CurrentUser, query: Q):
    full = await graph.build(db, query, user)
    sub = graph.explore(full, node_id)
    node = next(n for n in sub["nodes"] if n["id"] == node_id)
    detail = None
    ref = node["entity_ref"]
    if ref:
        model = {"order": Order, "task": Task, "decision": Decision}.get(ref["type"])
        if model:
            detail = (
                await serialize_many(db, [await workflow.scoped(db, model, UUID(ref["id"]), user)], user)
            )[0]
        elif ref["type"] == "metric":
            context = {key: str(value) for key, value in full["context"].items() if value is not None}
            detail = {
                **node["metadata"],
                "breakdown_url": f"/api/v1/metrics/{ref['id']}/breakdown?" + urlencode(context),
            }
        else:
            model = {
                "alert": Alert,
                "department": Department,
                "order_event": OrderEvent,
                "mary_event": MaryEvent,
            }.get(ref["type"])
            if model:
                row = await db.get(model, UUID(ref["id"]))
                detail = columns(row) if row else None
    return {
        "data": {
            "detail": detail,
            "node": node,
            "edges": sub["edges"],
            "context": full["context"],
            "graph_revision": full["graph_revision"],
        }
    }


@router.get("/impact-map/edges/{edge_id}", response_model=Data[dict])
async def impact_edge(edge_id: str, db: DB, user: CurrentUser, query: Q):
    full = await graph.build(db, query, user)
    edge = next((e for e in full["edges"] if e["id"] == edge_id), None)
    if not edge:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Связь не найдена")
    return {"data": {"edge": edge, "context": full["context"], "graph_revision": full["graph_revision"]}}


@router.post("/impact-map/analyze", response_model=Data[AnalysisOut])
async def impact_analyze(payload: Analyze, db: DB, user: CurrentUser):
    return {"data": await ai.analyze(db, payload, user)}


@router.get("/management-actions", response_model=Page[ActionOut])
async def action_list(db: DB, user: CurrentUser, query: Annotated[ActionsQuery, Query()]):
    scope = department_scope(user, query.department_id)
    stmt = actions.statement(user)
    if scope:
        stmt = stmt.where(ManagementAction.department_id == scope)
    for name in ("status", "assignee_id", "type"):
        if getattr(query, name):
            stmt = stmt.where(getattr(ManagementAction, name) == getattr(query, name))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(ManagementAction.created_at.desc(), ManagementAction.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page([await actions.out(db, row, user) for row in rows], total, query.page, query.page_size)


@router.post("/management-actions", response_model=Data[ActionOut], status_code=201)
async def action_create(
    payload: ActionCreate, request: Request, db: DB, user: CurrentUser, idempotency_key: Key = None
):
    require_role(user, WRITE_ROLES)
    previous, hashed = await idempotency.begin(db, user, idempotency_key, "action.create", payload)
    if previous:
        await actions.get(db, UUID(previous.response_body["data"]["id"]), user)
        replay_allowed(previous.response_body, user)
        return JSONResponse(previous.response_body, status_code=201, headers={"Idempotency-Replayed": "true"})
    obj = await actions.create(db, payload, user, request)
    result = {"data": await actions.out(db, obj, user)}
    idempotency.remember(db, user, idempotency_key, "action.create", hashed, result)
    await db.commit()
    return result


@router.get("/management-actions/{identifier}", response_model=Data[ActionOut])
async def action_get(identifier: UUID, db: DB, user: CurrentUser):
    return {"data": await actions.out(db, await actions.get(db, identifier, user), user)}


@router.patch("/management-actions/{identifier}", response_model=Data[ActionOut])
async def action_patch(identifier: UUID, payload: ActionPatch, request: Request, db: DB, user: CurrentUser):
    obj = await actions.get(db, identifier, user, lock=True)
    await actions.edit(db, obj, payload, user, request)
    result = {"data": await actions.out(db, obj, user)}
    await db.commit()
    return result


@router.get("/management-actions/{identifier}/history", response_model=Page[dict])
async def action_history(
    identifier: UUID, db: DB, user: CurrentUser, query: Annotated[PaginationQuery, Query()]
):
    await actions.get(db, identifier, user)
    stmt = select(AuditLog).where(
        AuditLog.object_type == "management_action", AuditLog.object_id == identifier
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(AuditLog.created_at, AuditLog.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    # Deliberately exclude general audit metadata, network identifiers and user agents.
    items = [
        columns(row, exclude={"ip_address", "user_agent", "object_name", "error_message"}) for row in rows
    ]
    if user.role == "employee":
        # Project communication state only; do not leak linked objects from audit details.
        for item in items:
            item["details"] = None
            for field in ("old_values", "new_values"):
                item[field] = {
                    key: val
                    for key, val in (item[field] or {}).items()
                    if key in {"status", "version", "assignment_cycle"}
                }

    return page(items, total, query.page, query.page_size)


CommandName = Literal[
    "send",
    "acknowledge",
    "start",
    "resolve",
    "verify",
    "reject",
    "cancel",
    "reassign",
    "change-deadline",
    "request-change",
    "escalate",
]


@router.post("/management-actions/{identifier}/{command}", response_model=Data[ActionOut])
async def action_command(
    identifier: UUID,
    command: CommandName,
    payload: ActionCommand,
    request: Request,
    db: DB,
    user: CurrentUser,
    idempotency_key: Key = None,
):
    # Permission is checked again on replay, and the key covers the concrete command and object.
    obj = await actions.get(db, identifier, user, lock=True)
    if command in {"send", "verify", "cancel", "reassign", "change-deadline", "escalate"}:
        require_role(user, WRITE_ROLES)
    elif obj.assignee_id != user.id:
        raise ApiError(403, "AUTH_FORBIDDEN", "Действие доступно только получателю")
    operation = f"action.{command}.{identifier}"
    # Stored operation keys have a 64-character bound.
    operation = graph.digest(operation)
    previous, hashed = await idempotency.begin(db, user, idempotency_key, operation, payload)
    if previous:
        replay_allowed(previous.response_body, user)
        return JSONResponse(previous.response_body, status_code=200, headers={"Idempotency-Replayed": "true"})
    await actions.command(db, obj, command, payload, user, request)
    result = {"data": await actions.out(db, obj, user)}
    idempotency.remember(db, user, idempotency_key, operation, hashed, result, status_code=200)
    await db.commit()
    return result


@router.get("/notifications", response_model=Page[NotificationOut])
async def notification_list(db: DB, user: CurrentUser, query: Annotated[NotificationsQuery, Query()]):
    stmt = select(Notification).where(
        Notification.recipient_id == user.id,
        Notification.action_id.in_(actions.statement(user).with_only_columns(ManagementAction.id)),
    )
    if query.unread is not None:
        stmt = stmt.where(
            Notification.read_at.is_(None) if query.unread else Notification.read_at.is_not(None)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(Notification.created_at.desc(), Notification.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page([NotificationOut.model_validate(row) for row in rows], total, query.page, query.page_size)


@router.post("/notifications/{identifier}/{command}", response_model=Data[NotificationOut])
async def notification_update(
    identifier: UUID, command: Literal["delivered", "read"], db: DB, user: CurrentUser, request: Request
):
    row = await db.scalar(
        select(Notification)
        .where(Notification.id == identifier, Notification.recipient_id == user.id)
        .with_for_update()
    )
    if not row:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Уведомление не найдено")
    obj = await actions.get(db, row.action_id, user)
    field = "delivered_at" if command == "delivered" else "read_at"
    if getattr(row, field) is None:
        setattr(row, field, datetime.now(UTC))
        actions.event(db, obj, "notification_" + command, user, request, details={"notification_id": row.id})
    await db.commit()
    return {"data": row}


@router.get("/management-actions/{identifier}/delivery", response_model=Page[dict])
async def delivery_status(
    identifier: UUID, db: DB, user: CurrentUser, query: Annotated[PaginationQuery, Query()]
):
    await actions.get(db, identifier, user)
    require_role(user, WRITE_ROLES)
    stmt = select(NotificationOutbox).where(NotificationOutbox.action_id == identifier)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(NotificationOutbox.created_at, NotificationOutbox.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page([columns(row) for row in rows], total, query.page, query.page_size)


@router.post("/management-actions/{identifier}/delivery/{outbox_id}/retry", response_model=Data[dict])
async def delivery_retry(identifier: UUID, outbox_id: UUID, db: DB, user: CurrentUser, request: Request):
    obj = await actions.get(db, identifier, user, lock=True)
    require_role(user, WRITE_ROLES)
    row = await db.scalar(
        select(NotificationOutbox)
        .where(NotificationOutbox.id == outbox_id, NotificationOutbox.action_id == identifier)
        .with_for_update()
    )
    if not row:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Доставка не найдена")
    if row.status != "failed":
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Повтор доступен для failed")
    row.status, row.attempts, row.available_at = "pending", 0, datetime.now(UTC)
    actions.event(db, obj, "notification_retry", user, request, details={"outbox_id": row.id})
    await db.commit()
    return {"data": columns(row)}


@router.get("/responsibilities/departments/{department_id}", response_model=Data[dict | None])
async def department_get(department_id: UUID, db: DB, user: CurrentUser):
    row = await responsibility.department_assignment(db, department_id, user)
    return {"data": columns(row) if row else None}


@router.put("/responsibilities/departments/{department_id}", response_model=Data[dict])
async def department_put(
    department_id: UUID, payload: DepartmentAssignment, request: Request, db: DB, user: CurrentUser
):
    await db.execute(text(f"SELECT pg_advisory_xact_lock({RESPONSIBILITY})"))
    row = await responsibility.department_assignment(db, department_id, user, payload, request)
    result = columns(row)
    await db.commit()
    return {"data": result}


@router.get("/responsibilities/metrics/{code}", response_model=Data[dict | None])
async def metric_get(code: str, db: DB, user: CurrentUser, department_id: UUID | None = None):
    row = await responsibility.metric_assignment(db, code, department_id, user)
    return {"data": columns(row) if row else None}


@router.put("/responsibilities/metrics/{code}", response_model=Data[dict])
async def metric_put(code: str, payload: MetricAssignment, request: Request, db: DB, user: CurrentUser):
    await db.execute(text(f"SELECT pg_advisory_xact_lock({RESPONSIBILITY})"))
    row = await responsibility.metric_assignment(db, code, payload.department_id, user, payload, request)
    result = columns(row)
    await db.commit()
    return {"data": result}


@router.post("/integrations/mary/events", response_model=Data[dict])
async def mary_events(payload: MaryBatch, request: Request, db: DB, user: CurrentUser):
    result = await mary.receive(db, payload, user, request)
    await db.commit()
    return {"data": result}
