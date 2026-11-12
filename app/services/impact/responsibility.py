from sqlalchemy import select

from app.core.exceptions import ApiError
from app.core.permissions import department_scope, require_role
from app.models import Metric, User
from app.models.impact import DepartmentResponsibility, MetricResponsibility
from app.services import audit, workflow


async def recipient(db, identifier, department):
    found = await db.get(User, identifier) if identifier else None
    if (
        not found
        or not found.is_active
        or found.role not in {"admin", "director", "manager", "employee"}
        or (found.role in {"manager", "employee"} and found.department_id != department)
    ):
        raise ApiError(422, "RECIPIENT_UNAVAILABLE", "Получатель недоступен в этой области")
    return found


async def default_recipient(db, code, department):
    if code:
        row = await db.scalar(
            select(MetricResponsibility).where(
                MetricResponsibility.metric_code == code, MetricResponsibility.department_id == department
            )
        )
        if row:
            return row.owner_id
    row = await db.scalar(
        select(DepartmentResponsibility).where(DepartmentResponsibility.department_id == department)
    )
    return row.head_id if row else None


async def escalation_recipient(db, action):
    row = await db.scalar(
        select(DepartmentResponsibility).where(DepartmentResponsibility.department_id == action.department_id)
    )
    if not row:
        return None
    identifier = row.director_id if row.head_id == action.assignee_id else row.head_id
    if identifier == action.assignee_id:
        return None
    try:
        found = await recipient(db, identifier, action.department_id)
    except ApiError:
        return None
    if identifier == row.director_id and found.role != "director":
        return None
    if identifier == row.head_id and found.role not in {"manager", "director", "admin"}:
        return None
    return found.id


async def department_assignment(db, department, user, payload=None, request=None):
    require_role(user, {"admin", "director", "manager", "analyst"})
    department_scope(user, department)
    row = await db.scalar(
        select(DepartmentResponsibility)
        .where(DepartmentResponsibility.department_id == department)
        .with_for_update()
    )
    if payload is None:
        return row
    require_role(user, {"admin", "director"})
    await workflow.active_department(db, department)
    head = await recipient(db, payload.head_id, department)
    director = await recipient(db, payload.director_id, department)
    if (
        head.role not in {"manager", "director", "admin"}
        or director.role != "director"
        or head.id == director.id
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Нужны руководитель и отдельный director для эскалации")
    if payload.version != (row.version if row else 0):
        raise ApiError(409, "VERSION_CONFLICT", "Назначение уже изменено")
    if not row:
        row = DepartmentResponsibility(
            department_id=department, head_id=head.id, director_id=director.id, version=1
        )
        db.add(row)
    else:
        row.head_id, row.director_id, row.version = head.id, director.id, row.version + 1
    await db.flush()
    await db.refresh(row)
    audit.record(
        db,
        "responsibility.department",
        "department_responsibility",
        actor=user,
        object_id=row.id,
        new={"head_id": row.head_id, "director_id": row.director_id, "version": row.version},
        request=request,
    )
    return row


async def metric_assignment(db, code, department, user, payload=None, request=None):
    require_role(user, {"admin", "director", "manager", "analyst"})
    department = department_scope(user, department)
    if not await db.scalar(select(Metric.id).where(Metric.code == code)):
        raise ApiError(404, "RESOURCE_NOT_FOUND", "KPI не найден")
    row = await db.scalar(
        select(MetricResponsibility)
        .where(MetricResponsibility.metric_code == code, MetricResponsibility.department_id == department)
        .with_for_update()
    )
    if payload is None:
        return row
    require_role(user, {"admin", "director"})
    owner = await recipient(db, payload.owner_id, department)
    if payload.version != (row.version if row else 0):
        raise ApiError(409, "VERSION_CONFLICT", "Назначение уже изменено")
    if department:
        await workflow.active_department(db, department)
    if not row:
        row = MetricResponsibility(metric_code=code, department_id=department, owner_id=owner.id, version=1)
        db.add(row)
    else:
        row.owner_id, row.version = owner.id, row.version + 1
    await db.flush()
    await db.refresh(row)
    audit.record(
        db,
        "responsibility.metric",
        "metric_responsibility",
        actor=user,
        object_id=row.id,
        new={"owner_id": owner.id, "version": row.version},
        request=request,
    )
    return row
