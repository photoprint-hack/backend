from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.permissions import WRITE_ROLES, require_role
from app.models import AuditLog, Decision, DecisionHistory, Order, OrderEvent, Task, User
from app.schemas.common import Data, Page, page
from app.schemas.shared.events import ChangeEvent
from app.schemas.shared.query import BusinessQuery
from app.schemas.workflow.decisions import DecisionCreate, DecisionOut, DecisionPatch, DecisionsQuery
from app.schemas.workflow.orders import OrderCreate, OrderEventOut, OrderOut, OrderPatch, OrdersQuery
from app.schemas.workflow.tasks import TaskCreate, TaskOut, TaskPatch, TasksQuery
from app.services import audit, idempotency, workflow
from app.services.serialization import columns, serialize_many

router = APIRouter(tags=["operations"])
Key = Annotated[UUID | None, Header(alias="Idempotency-Key")]
Q = Annotated[BusinessQuery, Query()]


async def collection(model, query, db, user):
    rows, total = await workflow.list_objects(db, model, query, user)
    return page(await serialize_many(db, rows, user), total, query.page, query.page_size)


async def created(model, payload, key, db, user, request):
    require_role(user, WRITE_ROLES)
    operation = {Order: "order.create", Decision: "decision.create", Task: "task.create"}[model]
    previous, digest = await idempotency.begin(db, user, key, operation, payload)
    if previous:
        await workflow.scoped(db, model, UUID(previous.response_body["data"]["id"]), user)
        return JSONResponse(
            status_code=previous.response_status,
            content=previous.response_body,
            headers={"Idempotency-Replayed": "true"},
        )
    if model is Order:
        from sqlalchemy import text

        await db.execute(text("SELECT pg_advisory_xact_lock(178901234)"))
    obj = await workflow.create(db, model, payload, user, request)
    if model is Order:
        from app.services.analytics import recalculate

        await recalculate(db, actor=user, request=request)
    schema = {Order: OrderOut, Decision: DecisionOut, Task: TaskOut}[model]
    content = {
        "data": schema.model_validate((await serialize_many(db, [obj], user))[0]).model_dump(mode="json")
    }
    idempotency.remember(db, user, key, operation, digest, content)
    await db.commit()
    return content


async def modified(model, identifier, payload, db, user, request):
    if model is Order:
        from sqlalchemy import text

        await db.execute(text("SELECT pg_advisory_xact_lock(178901234)"))
    obj = await workflow.scoped(db, model, identifier, user, lock=True)
    await workflow.patch(db, model, obj, payload, user, request)
    if model is Order:
        from app.services.analytics import recalculate

        await recalculate(db, actor=user, request=request)
    content = {"data": (await serialize_many(db, [obj], user))[0]}
    await db.commit()
    return content


@router.get("/orders", response_model=Page[OrderOut])
async def orders(db: DB, user: CurrentUser, query: Annotated[OrdersQuery, Query()]):
    return await collection(Order, query, db, user)


@router.post("/orders", response_model=Data[OrderOut], status_code=201)
async def create_order(
    payload: OrderCreate, request: Request, db: DB, user: CurrentUser, idempotency_key: Key = None
):
    return await created(Order, payload, idempotency_key, db, user, request)


@router.get("/orders/{identifier}", response_model=Data[OrderOut])
async def get_order(identifier: UUID, db: DB, user: CurrentUser):
    return {"data": (await serialize_many(db, [await workflow.scoped(db, Order, identifier, user)], user))[0]}


@router.patch("/orders/{identifier}", response_model=Data[OrderOut])
async def patch_order(identifier: UUID, payload: OrderPatch, request: Request, db: DB, user: CurrentUser):
    return await modified(Order, identifier, payload, db, user, request)


@router.get("/orders/{identifier}/events", response_model=Page[OrderEventOut])
async def order_events(
    identifier: UUID,
    db: DB,
    user: CurrentUser,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    await workflow.scoped(db, Order, identifier, user)
    stmt = select(OrderEvent).where(OrderEvent.order_id == identifier)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(OrderEvent.occurred_at, OrderEvent.id)
            .offset((page_number - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    actors = {
        x.id: x
        for x in (
            await db.scalars(select(User).where(User.id.in_({row.actor_id for row in rows if row.actor_id})))
        ).all()
    }
    items = []
    for row in rows:
        item = columns(row, exclude={"actor_id"})
        person = actors.get(row.actor_id)
        item["actor"] = {"id": person.id, "full_name": person.full_name} if person else None
        items.append(item)
    return page(items, total, page_number, page_size)


@router.get("/decisions", response_model=Page[DecisionOut])
async def decisions(db: DB, user: CurrentUser, query: Annotated[DecisionsQuery, Query()]):
    return await collection(Decision, query, db, user)


@router.post("/decisions", response_model=Data[DecisionOut], status_code=201)
async def create_decision(
    payload: DecisionCreate, request: Request, db: DB, user: CurrentUser, idempotency_key: Key = None
):
    return await created(Decision, payload, idempotency_key, db, user, request)


@router.get("/decisions/{identifier}", response_model=Data[DecisionOut])
async def get_decision(identifier: UUID, db: DB, user: CurrentUser):
    return {
        "data": (await serialize_many(db, [await workflow.scoped(db, Decision, identifier, user)], user))[0]
    }


@router.patch("/decisions/{identifier}", response_model=Data[DecisionOut])
async def patch_decision(
    identifier: UUID, payload: DecisionPatch, request: Request, db: DB, user: CurrentUser
):
    return await modified(Decision, identifier, payload, db, user, request)


async def history(model, identifier, db, user, page_number, page_size):
    await workflow.scoped(db, model, identifier, user)
    if model is Decision:
        if user.role == "employee":
            raise ApiError(403, "AUTH_FORBIDDEN", "История решения недоступна")
        stmt = select(DecisionHistory).where(DecisionHistory.decision_id == identifier)
        sort = DecisionHistory.created_at
        pk = DecisionHistory.id
    else:
        stmt = select(AuditLog).where(
            AuditLog.object_type == "task", AuditLog.object_id == identifier, AuditLog.status == "success"
        )
        sort = AuditLog.created_at
        pk = AuditLog.id
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.scalars(
            stmt.order_by(sort.desc(), pk).offset((page_number - 1) * page_size).limit(page_size)
        )
    ).all()
    ids = {getattr(x, "changed_by", getattr(x, "user_id", None)) for x in rows}
    actors = {x.id: x for x in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
    items = []
    for row in rows:
        actor = actors.get(getattr(row, "changed_by", getattr(row, "user_id", None)))
        items.append(
            {
                "id": row.id,
                "object_type": "decision" if model is Decision else "task",
                "object_id": identifier,
                "action": row.action,
                "changed_by": {"id": actor.id, "full_name": actor.full_name} if actor else None,
                "old_values": row.old_values or {},
                "new_values": row.new_values or {},
                "comment": row.comment if model is Decision else (row.details or {}).get("comment"),
                "created_at": row.created_at,
            }
        )
    return page(items, total, page_number, page_size)


@router.get("/decisions/{identifier}/history", response_model=Page[ChangeEvent])
async def decision_history(
    identifier: UUID,
    db: DB,
    user: CurrentUser,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await history(Decision, identifier, db, user, page_number, page_size)


@router.get("/tasks", response_model=Page[TaskOut])
async def tasks(db: DB, user: CurrentUser, query: Annotated[TasksQuery, Query()]):
    return await collection(Task, query, db, user)


@router.post("/tasks", response_model=Data[TaskOut], status_code=201)
async def create_task(
    payload: TaskCreate, request: Request, db: DB, user: CurrentUser, idempotency_key: Key = None
):
    return await created(Task, payload, idempotency_key, db, user, request)


@router.get("/tasks/{identifier}", response_model=Data[TaskOut])
async def get_task(identifier: UUID, db: DB, user: CurrentUser):
    return {"data": (await serialize_many(db, [await workflow.scoped(db, Task, identifier, user)], user))[0]}


@router.patch("/tasks/{identifier}", response_model=Data[TaskOut])
async def patch_task(identifier: UUID, payload: TaskPatch, request: Request, db: DB, user: CurrentUser):
    return await modified(Task, identifier, payload, db, user, request)


@router.delete("/tasks/{identifier}", status_code=204)
async def archive_task(identifier: UUID, request: Request, db: DB, user: CurrentUser):
    require_role(user, {"admin"})
    obj = await workflow.scoped(db, Task, identifier, user, lock=True)
    from app.models.impact import ManagementAction
    from app.services.impact.actions import TERMINAL, event, touch

    for action in (
        await db.scalars(
            select(ManagementAction).where(
                ManagementAction.task_id == obj.id, ManagementAction.status.not_in(TERMINAL)
            )
        )
    ).all():
        action.status = "cancelled"
        touch(action)
        event(db, action, "cancel", user, request, details={"reason": "task.archived"})
    obj.deleted_at = datetime.now(UTC)
    audit.record(
        db, "task.archived", "task", actor=user, object_id=obj.id, object_name=obj.title, request=request
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/tasks/{identifier}/history", response_model=Page[ChangeEvent])
async def task_history(
    identifier: UUID,
    db: DB,
    user: CurrentUser,
    page_number: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await history(Task, identifier, db, user, page_number, page_size)
