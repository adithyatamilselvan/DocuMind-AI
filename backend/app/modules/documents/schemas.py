from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.core.ids import PyId
from app.modules.documents.states import DocumentStatus


def _norm_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = " ".join(t.lower().split())
        if t and len(t) <= 40 and t not in out:
            out.append(t)
    if len(out) > 20:
        raise ValueError("At most 20 tags")
    return out


Tags = Annotated[list[str], AfterValidator(_norm_tags)]


class DocumentOut(BaseModel):
    id: PyId
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus
    error: str | None = None
    category: str | None = None
    tags: list[str]
    collection_ids: list[PyId]
    page_count: int | None = None
    language: str | None = None
    version_count: int
    access_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> "DocumentOut":
        return cls(
            id=d["_id"], title=d["title"], filename=d["filename"], mime_type=d["mime_type"],
            size_bytes=d["size_bytes"], sha256=d["sha256"], status=d["status"],
            error=d.get("error"), category=d.get("category"), tags=d.get("tags", []),
            collection_ids=d.get("collection_ids", []), page_count=d.get("page_count"),
            language=d.get("language"), version_count=d.get("version_count", 1),
            access_count=d.get("access_count", 0), created_at=d["created_at"],
            updated_at=d["updated_at"],
        )  # fmt: skip


SortField = Literal["created_at", "updated_at", "title", "size_bytes", "access_count"]


class DocumentQuery(BaseModel):
    q: str | None = Field(None, max_length=200)
    status: DocumentStatus | None = None
    category: str | None = Field(None, max_length=60)
    tag: str | None = Field(None, max_length=40)
    collection_id: str | None = None
    mime_type: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    sort: SortField = "created_at"
    order: Literal["asc", "desc"] = "desc"


class UpdateDocumentIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    category: str | None = Field(None, max_length=60)
    tags: Tags | None = None
    collection_ids: list[str] | None = None


class BulkIn(BaseModel):
    action: Literal[
        "delete", "add_tags", "remove_tags", "add_to_collection", "remove_from_collection",
        "set_category",
    ]  # fmt: skip
    ids: list[str] = Field(min_length=1, max_length=200)
    tags: Tags | None = None
    collection_id: str | None = None
    category: str | None = Field(None, max_length=60)


class BulkOut(BaseModel):
    affected: int
