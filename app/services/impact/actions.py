from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import WRITE_ROLES, department_scope, require_role
from app.models import Alert, Decision, Order, Task
from app.models.impact import ManagementAction
from app.schemas.impact import ActionOut
from app.schemas.workflow.tasks import TaskCreate, TaskPatch
from app.services import analytics, audit, workflow
from app.services.impact import calendar, responsibility
from app.services.serialization import columns

TERMINAL = {"verified", "rejected", "cancelled"}
COMMANDS = {
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
}


def statement(user):
    stmt = select(ManagementAction)
    if user.role == "employee":
        return stmt.where(ManagementAction.assignee_id == user.id, ManagementAction.status != "draft")
    scope = department_scope(user)
    return stmt.where(ManagementAction.department_id == scope) if scope else stmt


async def get(db, identifier, user, lock=False):
    if lock:
        await db.execute(text("SELECT pg_advisory_xact_lock(178901235)"))
    stmt = statement(user).where(ManagementAction.id == identifier)
    if lock:
        stmt = stmt.with_for_update()
    obj = await db.scalar(stmt)
    if not obj:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Обращение не найдено")
    return obj


def event(db, obj, name, user=None, request=None, old=None, details=None):
    if user is None and request is None:
        from app.services.impact.graph import digest

        job_id = uuid5(
            NAMESPACE_URL, f"photoprint:impact-job:{obj.id}:{name}:{obj.assignment_cycle}:{digest(details)}"
        )
        request = SimpleNamespace(state=SimpleNamespace(request_id=job_id), client=None, headers={})
    audit.record(
        db,
        "management_action." + name,
        "management_action",
        actor=user,
        object_id=obj.id,
        old=old,
        new=columns(obj, exclude={"context", "scoped_context", "updated_at"}),
        details=details,
        request=request,
    )


async def out(db, obj, user):
    value = columns(obj, exclude={"planned_deadline", "scoped_context"})
    if user.role in {"manager", "employee"}:
        value["context"] = obj.scoped_context
    task = await db.get(Task, obj.task_id) if obj.task_id else None
    value["assignee_id"] = task.assignee_id if task and obj.status != "draft" else obj.assignee_id
    value["execution_due_at"] = task.deadline if task and obj.status != "draft" else obj.planned_deadline
    value["execution_status"] = task.status if task else None
    now = datetime.now(UTC)
    value["response_overdue"] = bool(
        obj.status not in TERMINAL
        and obj.sent_at
        and not obj.acknowledged_at
        and obj.response_due_at
        and now > obj.response_due_at
    )
    value["response_was_late"] = bool(
        obj.acknowledged_at and obj.response_due_at and obj.acknowledged_at > obj.response_due_at
    )
    value["execution_overdue"] = bool(
        obj.status not in TERMINAL
        and task
        and not task.deleted_at
        and task.status in {"new", "in_progress"}
        and now > task.deadline
    )
    allowed = ["read", "history"]
    if obj.status not in TERMINAL and user.role in WRITE_ROLES:
        allowed += (
            ["edit", "send"]
            if obj.status == "draft"
            else ["cancel", "reassign", "change-deadline", "escalate"]
        )
        if obj.status == "resolved" and user.id != value["assignee_id"]:
            allowed.append("verify")
    if user.id == value["assignee_id"] and obj.status not in TERMINAL:
        allowed += {
            "sent": ["acknowledge", "reject"],
            "acknowledged": ["start", "resolve", "reject"],
            "in_progress": ["resolve"],
        }.get(obj.status, [])
        allowed.append("request-change")
    if (
        user.id == value["assignee_id"]
        and obj.status in {"in_progress", "resolved"}
        and not obj.acknowledged_at
    ):
        allowed.append("acknowledge")
    if user.id == value["assignee_id"] and obj.status == "resolved" and not obj.result:
        allowed.append("resolve")
    value["allowed_actions"] = allowed
    # An assigned communication does not grant access to arbitrary linked business objects.
    if user.role == "employee":
        for field, model in (("order_id", Order), ("decision_id", Decision), ("alert_id", Alert)):
            identifier = value[field]
            if identifier:
                try:
                    await workflow.scoped(db, model, identifier, user)
                except ApiError:
                    value[field] = None
        if value["source_ref"]:
            from app.schemas.impact import EntityRef

            try:
                await validate_refs(
                    db, user, obj.department_id, [EntityRef.model_validate(value["source_ref"])]
                )
            except ApiError:
                value["source_ref"] = None
        value["metric_code"] = None
        value["context"] = {key: val for key, val in value["context"].items() if key != "problem"}
        safe_refs = []
        from app.schemas.impact import EntityRef

        for ref in value["result_refs"]:
            try:
                await validate_refs(db, user, obj.department_id, [EntityRef.model_validate(ref)])
                safe_refs.append(ref)
            except ApiError:
                pass
        value["result_refs"] = safe_refs
    return ActionOut.model_validate(value).model_dump(mode="json")


async def validate_refs(db, user, department, refs):
    for ref in refs:
        if ref.type == "metric":
            if ref.id not in {d[0] for d in analytics.DEFINITIONS} or user.role == "employee":
                raise ApiError(404, "RESOURCE_NOT_FOUND", "Источник недоступен")
            continue
        model = {"order": Order, "task": Task, "decision": Decision, "alert": Alert}.get(ref.type)
        if not model:
            raise ApiError(
                422, "VALIDATION_ERROR", "Допустимы ссылки на KPI, заказ, задачу, решение или Alert"
            )
        try:
            identifier = UUID(ref.id)
        except ValueError:
            raise ApiError(422, "VALIDATION_ERROR", "Некорректная ссылка") from None
        row = await workflow.scoped(db, model, identifier, user)
        if row.department_id != department:
            raise ApiError(422, "VALIDATION_ERROR", "Источник из другой области")


async def create(db, payload, user, request):
    require_role(user, WRITE_ROLES)
    department_scope(user, payload.department_id)
    await workflow.active_department(db, payload.department_id)
    from app.services.impact.snapshots import capture_pair

    context, scoped_context = await capture_pair(db, payload, user)
    if payload.source_ref:
        await validate_refs(db, user, payload.department_id, [payload.source_ref])
    await workflow.validate_links(
        db, user, payload.department_id, payload.decision_id, payload.alert_id, payload.order_id
    )
    assignee_id = payload.assignee_id or await responsibility.default_recipient(
        db, payload.metric_code, payload.department_id
    )
    if assignee_id:
        await responsibility.recipient(db, assignee_id, payload.department_id)
    if payload.task_id:
        task = await workflow.scoped(db, Task, payload.task_id, user)
        if task.department_id != payload.department_id:
            raise ApiError(422, "VALIDATION_ERROR", "Задача из другой области")
    if payload.type != "task" and (payload.task_id or payload.execution_due_at):
        raise ApiError(422, "VALIDATION_ERROR", "Срок исполнения и Task задаются только поручению")
    from fastapi.encoders import jsonable_encoder

    obj = ManagementAction(
        **payload.model_dump(exclude={"context", "source_ref", "assignee_id", "execution_due_at"}),
        context=jsonable_encoder(context),
        scoped_context=scoped_context,
        source_ref=payload.source_ref.model_dump() if payload.source_ref else None,
        assignee_id=assignee_id,
        planned_deadline=payload.execution_due_at,
        author_id=user.id,
        status="draft",
    )
    db.add(obj)
    await db.flush()
    event(db, obj, "created", user, request)
    return obj


async def edit(db, obj, payload, user, request):
    require_role(user, WRITE_ROLES)
    if obj.status != "draft":
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Редактируется только черновик")
    check_version(obj, payload.version)
    before = columns(obj, exclude={"context", "scoped_context"})
    if obj.type != "task" and payload.execution_due_at:
        raise ApiError(422, "VALIDATION_ERROR", "У напоминания нет срока исполнения")
    for name, value in payload.model_dump(exclude_unset=True, exclude={"version"}).items():
        if name == "assignee_id" and value:
            await responsibility.recipient(db, value, obj.department_id)
        setattr(obj, "planned_deadline" if name == "execution_due_at" else name, value)
    touch(obj)
    event(db, obj, "edited", user, request, old=before)


def check_version(obj, version):
    if obj.version != version:
        raise ApiError(409, "VERSION_CONFLICT", "Обращение изменено; обновите данные")


def touch(obj):
    obj.version += 1
    obj.updated_at = datetime.now(UTC)


def require_reason(payload):
    if not payload.reason:
        raise ApiError(422, "VALIDATION_ERROR", "Укажите причину")


async def task_for_update(db, obj):
    if not obj.task_id:
        return None
    task = await db.scalar(select(Task).where(Task.id == obj.task_id).with_for_update())
    if not task or task.deleted_at:
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Связанная задача архивирована")
    return task


async def command(db, obj, name, payload, user, request):
    from app.services.impact.notifications import enqueue, escalate

    if name not in COMMANDS:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Команда не найдена")
    permitted_fields = {
        "send": set(),
        "acknowledge": set(),
        "start": set(),
        "resolve": {"result", "result_refs"},
        "verify": {"verification_note"},
        "reject": {"reason"},
        "cancel": {"reason"},
        "reassign": {"reason", "assignee_id"},
        "change-deadline": {"reason", "execution_due_at", "response_due_at"},
        "request-change": {"reason", "assignee_id", "execution_due_at", "response_due_at"},
        "escalate": {"reason", "assignee_id"},
    }
    if payload.model_fields_set - {"version"} - permitted_fields[name]:
        raise ApiError(422, "VALIDATION_ERROR", "Поле не относится к выбранной команде")
    check_version(obj, payload.version)
    if obj.status in TERMINAL:
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Обращение завершено")
    leadership = name in {"send", "verify", "cancel", "reassign", "change-deadline", "escalate"}
    if leadership:
        require_role(user, WRITE_ROLES)
    elif obj.assignee_id != user.id:
        raise ApiError(403, "AUTH_FORBIDDEN", "Действие доступно только получателю")
    before = columns(obj, exclude={"context", "scoped_context"})
    now = datetime.now(UTC)
    task = await task_for_update(db, obj)
    if name == "send":
        if obj.status != "draft":
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Отправляется только черновик")
        if not obj.assignee_id:
            raise ApiError(422, "RESPONSIBLE_NOT_CONFIGURED", "Назначьте ответственного")
        await responsibility.recipient(db, obj.assignee_id, obj.department_id)
        await workflow.active_department(db, obj.department_id)
        await workflow.validate_links(
            db, user, obj.department_id, obj.decision_id, obj.alert_id, obj.order_id
        )
        if obj.type == "task":
            if task:
                # Serialize competing associations even when their action rows differ.
                linked = await db.scalar(
                    select(ManagementAction.id).where(
                        ManagementAction.task_id == task.id,
                        ManagementAction.id != obj.id,
                        ManagementAction.status.not_in(TERMINAL | {"draft"}),
                    )
                )
                if (
                    task.status not in {"new", "in_progress"}
                    or task.department_id != obj.department_id
                    or task.assignee_id != obj.assignee_id
                    or linked
                ):
                    raise ApiError(422, "VALIDATION_ERROR", "Задача не подходит для поручения")
            else:
                if not obj.planned_deadline:
                    raise ApiError(422, "VALIDATION_ERROR", "Укажите срок исполнения")
                task = await workflow.create(
                    db,
                    Task,
                    TaskCreate(
                        title=obj.title,
                        description=obj.text,
                        assignee_id=obj.assignee_id,
                        department_id=obj.department_id,
                        deadline=obj.planned_deadline,
                        priority=obj.priority,
                        decision_id=obj.decision_id,
                        alert_id=obj.alert_id,
                        order_id=obj.order_id,
                    ),
                    user,
                    request,
                )
                obj.task_id = task.id
        obj.status, obj.sent_at = "sent", now
        obj.assignment_cycle += 1
        obj.response_due_at = calendar.add_working_minutes(
            now, calendar.RESPONSE_MINUTES[obj.priority], get_settings().business_holidays
        )
        obj.calendar_version = calendar.version(get_settings().business_holidays)
        await enqueue(db, obj, obj.assignee_id, "action_sent", f"send:{obj.assignment_cycle}")
    elif name == "acknowledge":
        if obj.status not in {"sent", "in_progress", "resolved"} or obj.acknowledged_at:
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Подтверждение недоступно")
        obj.acknowledged_at = now
        if obj.status == "sent":
            obj.status = "acknowledged"
    elif name in {"start", "resolve"}:
        if obj.status not in (
            {"acknowledged"} if name == "start" else {"acknowledged", "in_progress", "resolved"}
        ):
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Сначала подтвердите получение")
        if name == "resolve":
            if obj.status == "resolved" and obj.result:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Результат уже сообщён")
            if not payload.result:
                raise ApiError(422, "VALIDATION_ERROR", "Укажите результат")
            await validate_refs(db, user, obj.department_id, payload.result_refs)
            obj.result, obj.result_refs = payload.result, [r.model_dump() for r in payload.result_refs]
            obj.resolved_at = now
        if task:
            # Existing workflow forbids new -> completed; perform the ordinary start first.
            if task.status == "new":
                await workflow.patch(
                    db, Task, task, TaskPatch(version=task.version, status="in_progress"), user, request
                )
            if name == "resolve" and task.status == "in_progress":
                await workflow.patch(
                    db, Task, task, TaskPatch(version=task.version, status="completed"), user, request
                )
            if task.status not in ({"in_progress"} if name == "start" else {"completed"}):
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Задача не допускает это действие")
        obj.status = "in_progress" if name == "start" else "resolved"
        if name == "resolve":
            await enqueue(db, obj, obj.author_id, "result_submitted", f"result:{obj.assignment_cycle}")
    elif name == "verify":
        if obj.status != "resolved":
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Ожидается результат")
        if user.id == obj.assignee_id:
            raise ApiError(403, "AUTH_FORBIDDEN", "Самопроверка запрещена")
        if not payload.verification_note:
            raise ApiError(422, "VALIDATION_ERROR", "Укажите результат проверки")
        obj.status, obj.verified_at, obj.reviewer_id = "verified", now, user.id
        obj.verification_note = payload.verification_note
    elif name in {"reject", "cancel"}:
        require_reason(payload)
        if name == "reject" and obj.status not in {"sent", "acknowledged"}:
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Нельзя отклонить это состояние")
        obj.status = "rejected" if name == "reject" else "cancelled"
    elif name == "reassign":
        previous_cycle = obj.assignment_cycle
        require_reason(payload)
        if obj.status in {"draft", "resolved"} or not payload.assignee_id:
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Переназначение недоступно")
        await responsibility.recipient(db, payload.assignee_id, obj.department_id)
        if payload.assignee_id == obj.assignee_id:
            raise ApiError(422, "VALIDATION_ERROR", "Выберите другого получателя")
        if task:
            await workflow.patch(
                db,
                Task,
                task,
                TaskPatch(version=task.version, assignee_id=payload.assignee_id, comment=payload.reason),
                user,
                request,
            )
        obj.assignee_id = payload.assignee_id
        obj.acknowledged_at, obj.status, obj.sent_at = None, "sent", now
        obj.assignment_cycle = previous_cycle + 1
        obj.escalation_level, obj.routing_issue = 0, None
        obj.response_due_at = calendar.add_working_minutes(
            now, calendar.RESPONSE_MINUTES[obj.priority], get_settings().business_holidays
        )
        obj.calendar_version = calendar.version(get_settings().business_holidays)
        await enqueue(db, obj, obj.assignee_id, "action_reassigned", f"reassign:{obj.assignment_cycle}")
    elif name == "change-deadline":
        require_reason(payload)
        if obj.status in {"draft", "resolved"} or not (payload.execution_due_at or payload.response_due_at):
            raise ApiError(422, "VALIDATION_ERROR", "Укажите срок активного обращения")
        if payload.response_due_at:
            if obj.acknowledged_at:
                raise ApiError(409, "INVALID_STATUS_TRANSITION", "Реакция уже получена")
            workflow.future_deadline(payload.response_due_at)
            obj.response_due_at = payload.response_due_at
        if payload.execution_due_at:
            if not task:
                raise ApiError(422, "VALIDATION_ERROR", "У обращения нет Task")
            await workflow.patch(
                db,
                Task,
                task,
                TaskPatch(version=task.version, deadline=payload.execution_due_at, comment=payload.reason),
                user,
                request,
            )
    elif name == "request-change":
        require_reason(payload)
        if obj.status == "draft":
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Обращение ещё не отправлено")
        if payload.assignee_id:
            await responsibility.recipient(db, payload.assignee_id, obj.department_id)
        await enqueue(db, obj, obj.author_id, "change_requested", f"change:{obj.version}")
    elif name == "escalate":
        require_reason(payload)
        if obj.status == "draft":
            raise ApiError(409, "INVALID_STATUS_TRANSITION", "Обращение ещё не отправлено")
        if not await escalate(db, obj, "manual", user, request, payload.reason, payload.assignee_id):
            raise ApiError(422, "RESPONSIBLE_NOT_CONFIGURED", "Нет новой допустимой ступени эскалации")
    touch(obj)
    event(db, obj, name, user, request, before, payload.model_dump(mode="json", exclude={"version"}))
    await db.flush()
    return obj


async def sync_task(db, task, user, request, old):
    """Called by the existing Task PATCH in the same transaction; acknowledge stays independent."""
    obj = await db.scalar(
        select(ManagementAction)
        .where(ManagementAction.task_id == task.id, ManagementAction.status.not_in(TERMINAL | {"draft"}))
        .with_for_update()
    )
    if not obj:
        return
    before = {"status": obj.status, "assignee_id": obj.assignee_id}
    if task.assignee_id != obj.assignee_id:
        await responsibility.recipient(db, task.assignee_id, obj.department_id)
        obj.assignee_id = task.assignee_id
        obj.assignment_cycle += 1
        obj.acknowledged_at, obj.sent_at = None, datetime.now(UTC)
        obj.status, obj.escalation_level = "sent", 0
        obj.response_due_at = calendar.add_working_minutes(
            obj.sent_at, calendar.RESPONSE_MINUTES[obj.priority], get_settings().business_holidays
        )
        obj.calendar_version = calendar.version(get_settings().business_holidays)
        from app.services.impact.notifications import enqueue

        await enqueue(db, obj, obj.assignee_id, "action_reassigned", f"reassign:{obj.assignment_cycle}")
    if task.status == "completed":
        obj.status, obj.resolved_at = "resolved", task.completed_at
    elif task.status == "in_progress" and old.get("status") != "in_progress":
        obj.status = "in_progress"
    touch(obj)
    event(
        db,
        obj,
        "task_synchronized",
        user,
        request,
        before,
        {"task_id": task.id, "deadline": task.deadline, "task_status": task.status},
    )
