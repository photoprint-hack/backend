from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common import Schema, Title

Role = Literal["admin", "director", "manager", "analyst", "employee"]
Password = Annotated[str, Field(min_length=12, max_length=128)]


class Login(Schema):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserOut(Schema):
    id: UUID
    email: EmailStr
    full_name: str
    role: Role
    department_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class Assignee(Schema):
    id: UUID
    full_name: str
    role: Role
    department_id: UUID | None


class UserCreate(Schema):
    email: EmailStr
    full_name: Title
    role: Role
    department_id: UUID | None = None
    temporary_password: Password

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def scoped_user(self):
        if self.role in ("manager", "employee") and not self.department_id:
            raise ValueError("Подразделение обязательно для этой роли")
        return self


class UserPatch(Schema):
    full_name: Title | None = None
    role: Role | None = None
    department_id: UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Передайте хотя бы одно поле")
        for key in self.model_fields_set - {"department_id"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} не может быть null")
        return self


class DepartmentOut(Schema):
    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class Tokens(Schema):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900


class LoginResult(Tokens):
    user: UserOut


class Success(Schema):
    success: Literal[True] = True
