from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.ids import PyId
from app.modules.rag.schemas import CitationOut, Filters


class ConversationOut(BaseModel):
    id: PyId
    title: str
    scope: Filters
    message_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> "ConversationOut":
        scope = {
            k: [str(i) for i in v] if isinstance(v, list) else v
            for k, v in d.get("scope", {}).items()
        }
        return cls(
            id=d["_id"], title=d["title"], scope=Filters(**scope),
            message_count=d.get("message_count", 0), created_at=d["created_at"],
            updated_at=d["updated_at"],
        )  # fmt: skip


class MessageOut(BaseModel):
    id: PyId
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut] = Field(default_factory=list)
    grounded: bool | None = None
    insufficient_evidence: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    feedback: Literal["up", "down"] | None = None
    created_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> "MessageOut":
        meta = d.get("meta", {})
        return cls(
            id=d["_id"], role=d["role"], content=d["content"],
            citations=[CitationOut(**c) for c in d.get("citations", [])],
            grounded=meta.get("grounded"), insufficient_evidence=meta.get("insufficient_evidence"),
            warnings=meta.get("warnings", []), feedback=(d.get("feedback") or {}).get("rating"),
            created_at=d["created_at"],
        )  # fmt: skip


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class CreateConversationIn(BaseModel):
    title: str | None = Field(None, max_length=120)
    scope: Filters = Field(default_factory=Filters)


class UpdateConversationIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    scope: Filters | None = None


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"] | None  # null clears the feedback
    comment: str | None = Field(None, max_length=1000)
