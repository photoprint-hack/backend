from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select, update
from starlette.concurrency import run_in_threadpool

from app.api.deps import DB, CurrentUser
from app.core.exceptions import ApiError
from app.core.permissions import READ_ROLES, department_scope, require_role
from app.core.security import hash_password
from app.models import Department, RefreshToken, User
from app.schemas.common import Data, Page, Schema, page
from app.schemas.identity import Assignee, DepartmentOut, Role, UserCreate, UserOut, UserPatch
from app.services.audit import record

router = APIRouter(tags=["identity"])


class UserQuery(Schema):
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)
    search: str | None = Query(None, min_length=1, max_length=200)
    role: Role | None = None
    department_id: UUID | None = None
    is_active: bool | None = None
    sort_by: Literal["full_name", "created_at", "email"] = "full_name"
    sort_order: Literal["asc", "desc"] = "asc"


class DepartmentQuery(Schema):
    page: int = Query(1, ge=1)
    page_size: int = Query(20, ge=1, le=100)
    search: str | None = Query(None, min_length=1, max_length=200)
    is_active: bool | None = None
    sort_by: Literal["name", "code"] = "name"
    sort_order: Literal["asc", "desc"] = "asc"


async def available_department(db, identifier: UUID | None):
    if identifier:
        department = await db.get(Department, identifier)
        if not department or not department.is_active:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Подразделение недоступно",
                {"department_id": "Выберите активное подразделение"},
            )


@router.get("/users", response_model=Page[UserOut] | Page[Assignee])
async def users(db: DB, user: CurrentUser, query: Annotated[UserQuery, Query()]):
    require_role(user, READ_ROLES)
    stmt = select(User)
    scope = department_scope(user, query.department_id)
    if user.role == "manager":
        stmt = stmt.where(or_(User.department_id == scope, User.role.in_(["admin", "director"])))
    elif scope:
        stmt = stmt.where(User.department_id == scope)
    if user.role != "admin":
        stmt = stmt.where(User.is_active.is_(True))
    elif query.is_active is not None:
        stmt = stmt.where(User.is_active == query.is_active)
    if query.role:
        stmt = stmt.where(User.role == query.role)
    if query.search:
        pattern = "%" + query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        # Email search is administrative; non-admin responses never leak email.
        stmt = stmt.where(
            or_(User.full_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\"))
            if user.role == "admin"
            else User.full_name.ilike(pattern, escape="\\")
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = getattr(User, query.sort_by)
    rows = (
        await db.scalars(
            stmt.order_by(col.desc() if query.sort_order == "desc" else col.asc(), User.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    schema = UserOut if user.role == "admin" else Assignee
    return page([schema.model_validate(row) for row in rows], total, query.page, query.page_size)


@router.get("/users/{identifier}", response_model=Data[UserOut])
async def get_user(identifier: UUID, db: DB, user: CurrentUser):
    require_role(user, {"admin"})
    found = await db.get(User, identifier)
    if not found:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Пользователь не найден")
    return {"data": found}


@router.post("/users", response_model=Data[UserOut], status_code=201)
async def create_user(payload: UserCreate, request: Request, db: DB, user: CurrentUser):
    require_role(user, {"admin"})
    await available_department(db, payload.department_id)
    hashed = await run_in_threadpool(hash_password, payload.temporary_password)
    found = User(**payload.model_dump(exclude={"temporary_password"}), password_hash=hashed)
    db.add(found)
    await db.flush()
    record(
        db,
        "user.created",
        "user",
        actor=user,
        object_id=found.id,
        object_name=found.full_name,
        new=payload.model_dump(exclude={"temporary_password"}),
        request=request,
    )
    await db.commit()
    return {"data": found}


@router.patch("/users/{identifier}", response_model=Data[UserOut])
async def patch_user(identifier: UUID, payload: UserPatch, request: Request, db: DB, user: CurrentUser):
    from datetime import UTC, datetime

    require_role(user, {"admin"})
    # Lock administrators in a deterministic order before changing any account.
    admins = (
        await db.scalars(
            select(User)
            .where(User.role == "admin", User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
    ).all()
    found = await db.get(User, identifier, with_for_update=True, populate_existing=True)
    if not found:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Пользователь не найден")
    changes = payload.model_dump(exclude_unset=True)
    if identifier == user.id and any(
        key in changes and changes[key] != getattr(found, key) for key in ("role", "is_active")
    ):
        raise ApiError(409, "DUPLICATE_RESOURCE", "Нельзя изменять собственную роль или активность")
    role = changes.get("role", found.role)
    department = changes.get("department_id", found.department_id)
    active = changes.get("is_active", found.is_active)
    if role in ("manager", "employee") and department is None:
        raise ApiError(
            422, "VALIDATION_ERROR", "Подразделение обязательно", {"department_id": "Выберите подразделение"}
        )
    if found.role == "admin" and found.is_active and (role != "admin" or not active) and len(admins) <= 1:
        raise ApiError(409, "DUPLICATE_RESOURCE", "Нельзя отключить последнего администратора")
    await available_department(db, department)
    old = {key: getattr(found, key) for key in changes}
    for key, value in changes.items():
        setattr(found, key, value)
    if not active or "role" in changes or "department_id" in changes:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == identifier, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    record(
        db,
        "user.updated",
        "user",
        actor=user,
        object_id=found.id,
        object_name=found.full_name,
        old=old,
        new=changes,
        request=request,
    )
    await db.flush()
    await db.refresh(found)
    await db.commit()
    return {"data": found}


@router.get("/departments", response_model=Page[DepartmentOut])
async def departments(db: DB, user: CurrentUser, query: Annotated[DepartmentQuery, Query()]):
    stmt = select(Department)
    if user.role in ("manager", "employee"):
        stmt = stmt.where(Department.id == user.department_id)
    if query.is_active is not None:
        stmt = stmt.where(Department.is_active == query.is_active)
    if query.search:
        stmt = stmt.where(
            Department.name.ilike(
                "%" + query.search.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = getattr(Department, query.sort_by)
    rows = (
        await db.scalars(
            stmt.order_by(col.desc() if query.sort_order == "desc" else col.asc(), Department.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    return page(rows, total, query.page, query.page_size)


@router.get("/departments/{identifier}", response_model=Data[DepartmentOut])
async def get_department(identifier: UUID, db: DB, user: CurrentUser):
    if user.role in ("manager", "employee") and identifier != user.department_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Подразделение не найдено")
    found = await db.get(Department, identifier)
    if not found:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Подразделение не найдено")
    return {"data": found}
