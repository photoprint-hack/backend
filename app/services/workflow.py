from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from sqlalchemy import exists, func, or_, select

from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.permissions import WRITE_ROLES, department_scope, require_role, scope_statement
from app.models import (
    Alert,
    Campaign,
    Customer,
    Deal,
    Decision,
    DecisionHistory,
    Department,
    Order,
    OrderEvent,
    Product,
    Task,
    User,
)
from app.services import audit
from app.services.serialization import columns


async def scoped(db, model, identifier, user, lock=False):
    stmt = scope_statement(select(model).where(model.id == identifier), model, user)
    if model is Task:
        stmt = stmt.where(Task.deleted_at.is_(None))
    if lock:
        stmt = stmt.with_for_update()
    found = await db.scalar(stmt)
    if not found:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Объект не найден")
    return found


async def assignee(db, identifier, department):
    found = await db.get(User, identifier)
    if (
        not found
        or not found.is_active
        or found.role not in {"admin", "director"}
        and found.department_id != department
    ):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Ответственный недоступен",
            {"assignee_id": "Выберите активного пользователя разрешённого подразделения"},
        )
    return found


async def active_department(db, identifier):
    found = await db.get(Department, identifier)
    if not found or not found.is_active:
        raise ApiError(422, "VALIDATION_ERROR", "Подразделение недоступно")


def future_deadline(value):
    if value <= datetime.now(UTC):
        raise ApiError(
            422, "VALIDATION_ERROR", "Срок должен быть в будущем", {"deadline": "Укажите будущий срок"}
        )


async def validate_links(db, user, department, decision_id=None, alert_id=None, order_id=None):
    linked = {}
    for model, identifier in [(Decision, decision_id), (Alert, alert_id), (Order, order_id)]:
        if identifier:
            found = await scoped(db, model, identifier, user)
            if found.department_id != department and not (
                model is Decision and found.department_id is None and user.role in {"admin", "director"}
            ):
                raise ApiError(422, "VALIDATION_ERROR", "Связанные объекты относятся к разным подразделениям")
            linked[model] = found
    if (
        Decision in linked
        and alert_id
        and linked[Decision].alert_id
        and linked[Decision].alert_id != alert_id
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Отклонение не соответствует решению")


async def create(db, model, payload, user, request):
    require_role(user, WRITE_ROLES)
    data = payload.model_dump()
    department = data.get("department_id")
    department_scope(user, department)
    if department is None and user.role == "manager":
        raise ApiError(422, "VALIDATION_ERROR", "Подразделение обязательно")
    if department:
        await active_department(db, department)
    if model is Order:
        product = await db.get(Product, data["product_id"])
        customer = await db.get(Customer, data["customer_id"])
        if not product or not product.is_active or not customer:
            raise ApiError(422, "VALIDATION_ERROR", "Клиент или продукт недоступен")
        if user.role == "manager":
            permitted = await db.scalar(
                select(Customer.id).where(
                    Customer.id == customer.id,
                    or_(
                        exists(
                            select(Order.id).where(
                                Order.customer_id == customer.id, Order.department_id == department
                            )
                        ),
                        exists(
                            select(Deal.id).where(
                                Deal.customer_id == customer.id, Deal.department_id == department
                            )
                        ),
                    ),
                )
            )
            if not permitted:
                raise ApiError(404, "RESOURCE_NOT_FOUND", "Клиент недоступен")
        if data.get("campaign_id") and not await db.get(Campaign, data["campaign_id"]):
            raise ApiError(422, "VALIDATION_ERROR", "Кампания не найдена")
        if data.get("crm_deal_id"):
            deal = await scoped(db, Deal, data["crm_deal_id"], user)
            if (
                deal.customer_id != customer.id
                or deal.department_id != department
                or deal.order_id is not None
            ):
                raise ApiError(422, "VALIDATION_ERROR", "Сделка не соответствует заказу")
        obj = Order(
            **data,
            order_number="FP-" + uuid4().hex.upper()[:16],
            standard_hours_per_unit=product.standard_hours_per_unit,
            status="new",
        )
    elif model is Decision:
        future_deadline(data["deadline"])
        await assignee(db, data["owner_id"], department)
        await validate_links(db, user, department, alert_id=data.get("alert_id"))
        obj = Decision(**data, created_by=user.id, status="new")
    else:
        future_deadline(data["deadline"])
        await assignee(db, data["assignee_id"], department)
        await validate_links(
            db,
            user,
            department,
            decision_id=data.get("decision_id"),
            alert_id=data.get("alert_id"),
            order_id=data.get("order_id"),
        )
        obj = Task(**data, created_by=user.id, status="new")
    db.add(obj)
    await db.flush()
    if model is Order:
        db.add(
            OrderEvent(
                order_id=obj.id,
                event_type="order_created",
                new_status="new",
                department_id=department,
                actor_id=user.id,
                source_system="platform",
                result="Заказ создан",
                occurred_at=datetime.now(UTC),
            )
        )
        if obj.crm_deal_id:
            linked = await db.get(Deal, obj.crm_deal_id)
            linked.order_id = obj.id
    elif model is Decision:
        db.add(
            DecisionHistory(
                decision_id=obj.id,
                changed_by=user.id,
                action="decision.created",
                old_values={},
                new_values=jsonable_encoder(columns(obj)),
            )
        )
    name = {Order: "order", Decision: "decision", Task: "task"}[model]
    audit.record(
        db,
        name + ".created",
        name,
        actor=user,
        object_id=obj.id,
        object_name=getattr(obj, "title", getattr(obj, "order_number", "")),
        new=columns(obj),
        request=request,
    )
    return obj


def transition(current, new, allowed):
    if current == new:
        return
    if new not in allowed.get(current, set()):
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Недопустимый переход статуса")


async def patch(db, model, obj, payload, user, request):
    data = payload.model_dump(exclude_unset=True)
    if model is Task and user.role == "employee":
        if set(data) - {"version", "status"}:
            raise ApiError(403, "AUTH_FORBIDDEN", "Разрешено менять только статус своей задачи")
    else:
        require_role(user, WRITE_ROLES)
    if data.pop("version") != obj.version:
        raise ApiError(409, "VERSION_CONFLICT", "Запись уже изменена; обновите данные")
    if obj.status in {"completed", "cancelled"}:
        raise ApiError(409, "INVALID_STATUS_TRANSITION", "Завершённый объект не редактируется")
    comment = data.pop("comment", None)
    old = columns(obj)
    status = data.get("status", obj.status)
    if model is Order:
        transition(
            obj.status,
            status,
            {"new": {"in_progress", "cancelled"}, "in_progress": {"completed", "cancelled"}},
        )
        for key, allowed in {
            "moderation_status": {
                "pending": {"approved", "rejected", "revision_required"},
                "revision_required": {"pending"},
            },
            "production_status": {
                "queued": {"in_progress", "blocked"},
                "blocked": {"queued"},
                "in_progress": {"completed", "blocked"},
            },
            "delivery_status": {
                "not_started": {"in_transit"},
                "in_transit": {"delivered", "delayed", "returned"},
                "delayed": {"in_transit", "delivered", "returned"},
                "delivered": {"returned"},
            },
        }.items():
            if key in data:
                transition(getattr(obj, key), data[key], allowed)
        production = data.get("production_status", obj.production_status)
        moderation = data.get("moderation_status", obj.moderation_status)
        delivery = data.get("delivery_status", obj.delivery_status)
        if production == "in_progress" and moderation != "approved":
            raise ApiError(422, "VALIDATION_ERROR", "Производство требует одобренной модерации")
        if delivery != "not_started" and production != "completed":
            raise ApiError(422, "VALIDATION_ERROR", "Доставка требует завершённого производства")
        completed = data.get("completed_at", obj.completed_at)
        if status == "completed" and (
            completed is None or completed < obj.created_at or completed > datetime.now(UTC)
        ):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Укажите корректную дату завершения",
                {"completed_at": "Не раньше создания и не позже текущего времени"},
            )
        if status != "completed" and completed is not None:
            raise ApiError(422, "VALIDATION_ERROR", "Дата завершения допустима только для completed")
    elif model is Decision:
        transition(
            obj.status,
            status,
            {
                "new": {"in_progress", "cancelled"},
                "in_progress": {"needs_review", "cancelled"},
                "needs_review": {"completed", "in_progress", "cancelled"},
            },
        )
        if status in {"needs_review", "completed"} and not data.get("actual_result", obj.actual_result):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Укажите фактический результат",
                {"actual_result": "Обязательное поле"},
            )
        if status == "completed" and not data.get("verification_note", obj.verification_note):
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Укажите результат проверки",
                {"verification_note": "Обязательное поле"},
            )
        if status == "cancelled" or obj.status == "needs_review" and status == "in_progress":
            if not comment:
                raise ApiError(
                    422, "VALIDATION_ERROR", "Требуется комментарий", {"comment": "Обязательное поле"}
                )
        if "owner_id" in data:
            await assignee(db, data["owner_id"], obj.department_id)
    else:
        transition(
            obj.status,
            status,
            {"new": {"in_progress", "cancelled"}, "in_progress": {"completed", "cancelled"}},
        )
        if status == "cancelled":
            if user.role == "employee":
                raise ApiError(403, "AUTH_FORBIDDEN", "Отменять задачу может руководитель")
            if not comment:
                raise ApiError(422, "VALIDATION_ERROR", "Требуется комментарий отмены")
        if "assignee_id" in data:
            await assignee(db, data["assignee_id"], obj.department_id)
    if "deadline" in data:
        future_deadline(data["deadline"])
    for key, value in data.items():
        setattr(obj, key, value)
    if status == "completed" and model is not Order:
        obj.completed_at = datetime.now(UTC)
    obj.version += 1
    obj.updated_at = datetime.now(UTC)
    await db.flush()
    name = {Order: "order", Decision: "decision", Task: "task"}[model]
    new = columns(obj)
    if model is Decision:
        db.add(
            DecisionHistory(
                decision_id=obj.id,
                changed_by=user.id,
                action="decision.updated",
                old_values=jsonable_encoder(old),
                new_values=jsonable_encoder(new),
                comment=comment,
            )
        )
    if model is Order:
        for key in ("status", "moderation_status", "production_status", "delivery_status"):
            if key in data and old[key] != data[key]:
                db.add(
                    OrderEvent(
                        order_id=obj.id,
                        event_type=key + "_changed",
                        old_status=old[key],
                        new_status=data[key],
                        department_id=obj.department_id,
                        actor_id=user.id,
                        source_system="platform",
                        result="Статус изменён",
                        occurred_at=datetime.now(UTC),
                    )
                )
    audit.record(
        db,
        name + ".updated",
        name,
        actor=user,
        object_id=obj.id,
        object_name=getattr(obj, "title", getattr(obj, "order_number", "")),
        old=old,
        new=new,
        details={"comment": comment} if comment else None,
        request=request,
    )
    return obj


async def list_objects(db, model, query, user):
    stmt = scope_statement(select(model), model, user, query.department_id)
    if model is Task:
        stmt = stmt.where(Task.deleted_at.is_(None))
    statuses = {
        Order: {"new", "in_progress", "completed", "cancelled"},
        Decision: {"new", "in_progress", "needs_review", "completed", "cancelled"},
        Task: {"new", "in_progress", "completed", "cancelled"},
        Alert: {"active", "acknowledged", "resolved"},
    }
    if query.status and query.status not in statuses.get(model, {query.status}):
        raise ApiError(422, "VALIDATION_ERROR", "Неизвестный статус")
    for key in [
        "status",
        "priority",
        "product_id",
        "customer_id",
        "campaign_id",
        "owner_id",
        "assignee_id",
        "alert_id",
        "decision_id",
        "order_id",
        "channel",
        "metric_code",
        "severity",
    ]:
        value = getattr(query, key, None)
        if value is not None and hasattr(model, key):
            stmt = stmt.where(getattr(model, key) == value)
    if query.search:
        pattern = "%" + query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if model is Order:
            stmt = stmt.where(
                or_(
                    Order.order_number.ilike(pattern, escape="\\"),
                    Order.customer_id.in_(
                        select(Customer.id).where(Customer.name.ilike(pattern, escape="\\"))
                    ),
                )
            )
        else:
            stmt = stmt.where(model.title.ilike(pattern, escape="\\"))
    zone = ZoneInfo(get_settings().report_timezone)
    if model is Alert:
        if query.date_from:
            stmt = stmt.where(Alert.period_end >= query.date_from)
        if query.date_to:
            stmt = stmt.where(Alert.period_start <= query.date_to)
        if query.has_decision is not None:
            condition = exists(select(Decision.id).where(Decision.alert_id == Alert.id))
            stmt = stmt.where(condition if query.has_decision else ~condition)
    else:
        if query.date_from:
            stmt = stmt.where(model.created_at >= datetime.combine(query.date_from, time.min, zone))
        if query.date_to:
            stmt = stmt.where(
                model.created_at < datetime.combine(query.date_to + timedelta(days=1), time.min, zone)
            )
    if hasattr(model, "deadline"):
        if getattr(query, "deadline_from", None):
            stmt = stmt.where(model.deadline >= query.deadline_from)
        if getattr(query, "deadline_to", None):
            stmt = stmt.where(model.deadline <= query.deadline_to)
        if query.overdue is not None:
            condition = (model.deadline < datetime.now(UTC)) & model.status.in_(
                ["new", "in_progress", "needs_review"]
            )
            stmt = stmt.where(condition if query.overdue else ~condition)
    allowed = (
        {"created_at", "updated_at", "deadline", "priority"}
        if model in {Task, Decision}
        else {"created_at", "due_at", "amount", "order_number"}
        if model is Order
        else {"created_at", "updated_at"}
    )
    if query.sort_by not in allowed:
        raise ApiError(422, "VALIDATION_ERROR", "Недопустимое поле сортировки")
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = getattr(model, query.sort_by)
    rows = (
        await db.scalars(
            stmt.order_by(col.desc() if query.sort_order == "desc" else col.asc(), model.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return rows, total
