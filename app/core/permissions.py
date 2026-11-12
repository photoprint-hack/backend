from uuid import UUID

from sqlalchemy import exists, select

from app.core.exceptions import ApiError
from app.models import Decision, Order, Task, User

READ_ROLES = {"admin", "director", "manager", "analyst"}
WRITE_ROLES = {"admin", "director", "manager"}


def require_role(user: User, roles: set[str]):
    if user.role not in roles:
        raise ApiError(403, "AUTH_FORBIDDEN", "Недостаточно прав")


def department_scope(user: User, requested: UUID | None = None) -> UUID | None:
    if user.role in ("manager", "employee"):
        if requested and requested != user.department_id:
            raise ApiError(403, "DEPARTMENT_ACCESS_DENIED", "Нет доступа к подразделению")
        return user.department_id
    return requested


def scope_statement(stmt, model, user: User, requested: UUID | None = None):
    scope = department_scope(user, requested)
    if user.role == "employee":
        if model is Task:
            return stmt.where(Task.assignee_id == user.id, Task.deleted_at.is_(None))
        if model is Order:
            return stmt.where(
                exists(
                    select(Task.id).where(
                        Task.order_id == Order.id, Task.assignee_id == user.id, Task.deleted_at.is_(None)
                    )
                )
            )
        if model is Decision:
            return stmt.where(
                exists(
                    select(Task.id).where(
                        Task.decision_id == Decision.id,
                        Task.assignee_id == user.id,
                        Task.deleted_at.is_(None),
                    )
                )
            )
        raise ApiError(403, "AUTH_FORBIDDEN", "Нет доступа к этому разделу")
    return stmt.where(model.department_id == scope) if scope else stmt
