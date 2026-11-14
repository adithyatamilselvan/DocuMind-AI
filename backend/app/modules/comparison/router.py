from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.ids import PyId, to_oid
from app.modules.auth.deps import DB
from app.modules.comparison import service
from app.modules.documents.deps import Queue
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/comparisons", tags=["comparison"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]
Config = Annotated[Settings, Depends(get_settings)]


class ComparisonOut(BaseModel):
    id: PyId
    kind: str
    title: str
    status: str
    error: str | None
    document_ids: list[PyId]
    result: dict[str, Any] | None
    verification: dict[str, int] | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any], with_result: bool = True) -> "ComparisonOut":
        return cls(
            id=d["_id"], kind=d["kind"], title=d["title"], status=d["status"], error=d.get("error"),
            document_ids=d["document_ids"], result=d.get("result") if with_result else None,
            verification=d.get("verification"), created_at=d["created_at"], updated_at=d["updated_at"],
        )  # fmt: skip


class CompareIn(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=5)
    aspects: list[str] | None = Field(None, max_length=8)
    title: str | None = Field(None, max_length=200)


class VersionsIn(BaseModel):
    document_id: str
    version_a: str | None = None  # defaults: previous version
    version_b: str | None = None  # defaults: current version


@router.post("", response_model=ComparisonOut, status_code=status.HTTP_202_ACCEPTED)
async def compare_documents(body: CompareIn, ctx: Editor, db: DB, queue: Queue, settings: Config):
    require_ai_consent(ctx, settings)
    ids = [to_oid(i, "Document") for i in dict.fromkeys(body.document_ids)]
    if len(ids) < 2:
        raise bad_request("Select at least two different documents", "too_few_documents")
    docs = {
        d["_id"]: d
        async for d in db.documents.find(
            {"_id": {"$in": ids}, "workspace_id": ctx.workspace_id, "deleted_at": None}
        )
    }
    if len(docs) != len(ids):
        raise not_found("Document not found")
    if any(d["status"] != "COMPLETED" for d in docs.values()):
        raise conflict("All documents must finish processing first", "not_ready")
    ordered = [docs[i] for i in ids]
    rec, job = await service.create_comparison(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user_id, kind="documents",
        title=body.title or " vs ".join(d["title"] for d in ordered)[:200], document_ids=ids,
        version_ids=[d["current_version_id"] for d in ordered], aspects=body.aspects,
    )  # fmt: skip
    await queue.enqueue(job["_id"])
    return ComparisonOut.from_doc(rec)


@router.post("/versions", response_model=ComparisonOut, status_code=status.HTTP_202_ACCEPTED)
async def compare_versions(body: VersionsIn, ctx: Editor, db: DB, queue: Queue):
    doc = await db.documents.find_one(
        {
            "_id": to_oid(body.document_id, "Document"),
            "workspace_id": ctx.workspace_id,
            "deleted_at": None,
        }
    )
    if not doc:
        raise not_found("Document not found")
    versions = [
        v
        async for v in db.document_versions.find({"document_id": doc["_id"]}).sort("version_no", 1)
    ]
    if len(versions) < 2 and not (body.version_a and body.version_b):
        raise bad_request("The document has only one version", "single_version")
    by_id = {str(v["_id"]): v for v in versions}
    a = by_id.get(body.version_a) if body.version_a else versions[-2]
    b = by_id.get(body.version_b) if body.version_b else versions[-1]
    if not a or not b or a["_id"] == b["_id"]:
        raise bad_request("Choose two different versions of this document", "bad_versions")
    rec, job = await service.create_comparison(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user_id, kind="versions",
        title=f"{doc['title']}: v{a['version_no']} vs v{b['version_no']}", document_ids=[doc["_id"]],
        version_ids=[a["_id"], b["_id"]], aspects=None,
    )  # fmt: skip
    await queue.enqueue(job["_id"])
    return ComparisonOut.from_doc(rec)


@router.get("", response_model=list[ComparisonOut])
async def list_comparisons(ctx: Viewer, db: DB):
    cursor = (
        db.document_comparisons.find({"workspace_id": ctx.workspace_id})
        .sort("created_at", -1)
        .limit(100)
    )
    return [ComparisonOut.from_doc(d, with_result=False) async for d in cursor]


@router.get("/{comparison_id}", response_model=ComparisonOut)
async def get_comparison(comparison_id: str, ctx: Viewer, db: DB):
    d = await db.document_comparisons.find_one(
        {"_id": to_oid(comparison_id, "Comparison"), "workspace_id": ctx.workspace_id}
    )
    if not d:
        raise not_found("Comparison not found")
    return ComparisonOut.from_doc(d)


@router.delete("/{comparison_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comparison(comparison_id: str, ctx: Editor, db: DB) -> Response:
    res = await db.document_comparisons.delete_one(
        {"_id": to_oid(comparison_id, "Comparison"), "workspace_id": ctx.workspace_id}
    )
    if not res.deleted_count:
        raise not_found("Comparison not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
