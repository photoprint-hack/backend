from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.common import Schema

Priority = Literal["low", "medium", "high", "critical"]


class VersionedPatch(Schema):
    version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def changed(self):
        if not self.model_fields_set - {"version"}:
            raise ValueError("Передайте изменяемые поля")
        nullable = {"completed_at", "actual_result", "verification_note", "comment"}
        for field in self.model_fields_set - {"version"} - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} не может быть null")
        return self
