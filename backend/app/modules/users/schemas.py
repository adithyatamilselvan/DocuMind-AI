from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.ids import PyId


class UserPreferences(BaseModel):
    theme: str = Field("system", pattern="^(light|dark|system)$")
    notifications_email: bool = True


class UserOut(BaseModel):
    id: PyId
    email: str
    name: str
    email_verified: bool
    preferences: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "UserOut":
        return cls(
            id=doc["_id"],
            email=doc["email"],
            name=doc["name"],
            email_verified=doc.get("email_verified", False),
            preferences=doc.get("preferences", {}),
            created_at=doc["created_at"],
        )


class UpdateProfileIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    preferences: UserPreferences | None = None
