from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.core.ids import PyId
from app.modules.workspaces.roles import Role


class WorkspaceSettings(BaseModel):
    # Explicit consent that document text may be sent to the configured external AI providers.
    ai_processing_consent: bool = False


class WorkspaceOut(BaseModel):
    id: PyId
    name: str
    slug: str
    role: Role
    settings: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_docs(cls, ws: dict[str, Any], role: Role) -> "WorkspaceOut":
        return cls(
            id=ws["_id"],
            name=ws["name"],
            slug=ws["slug"],
            role=role,
            settings=ws.get("settings", {}),
            created_at=ws["created_at"],
        )


class CreateWorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UpdateWorkspaceIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    settings: WorkspaceSettings | None = None


class MemberOut(BaseModel):
    user_id: PyId
    email: str
    name: str
    role: Role
    joined_at: datetime


class AddMemberIn(BaseModel):
    email: EmailStr
    role: Role = Role.viewer


class UpdateMemberIn(BaseModel):
    role: Role
