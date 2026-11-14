from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings, get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.ids import PyId, to_oid, utcnow
from app.modules.audit import service as audit
from app.modules.auth.deps import DB
from app.modules.documents import upload
from app.modules.documents.deps import Queue
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/knowledge-bases", tags=["knowledge-bases"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]
Config = Annotated[Settings, Depends(get_settings)]


class KbOut(BaseModel):
    id: PyId
    name: str
    description: str
    document_count: int
    index_status: str  # empty | ready | indexing | partial | failed
    created_at: datetime


class KbDocument(BaseModel):
    id: str
    title: str
    status: str
    error: str | None


class KbDetail(KbOut):
    documents: list[KbDocument]
    status_counts: dict[str, int]


class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=1000)


class KbPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)


class AddDocsIn(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=500)


async def _docs(db: DB, ctx: WorkspaceContext, kb: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        d
        async for d in db.documents.find(
            {"_id": {"$in": kb.get("document_ids", [])}, "workspace_id": ctx.workspace_id, "deleted_at": None}
        ).sort("title", 1)
    ]


def _index_status(docs: list[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for d in docs:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    if not docs:
        return "empty", counts
    done = counts.get("COMPLETED", 0)
    failed = counts.get("FAILED", 0)
    if done == len(docs):
        return "ready", counts
    if failed and done + failed == len(docs):
        return ("failed" if not done else "partial"), counts
    return "indexing", counts


async def _out(db: DB, ctx: WorkspaceContext, kb: dict[str, Any]) -> tuple[KbOut, list[dict[str, Any]], dict[str, int]]:
    docs = await _docs(db, ctx, kb)
    st, counts = _index_status(docs)
    out = KbOut(
        id=kb["_id"], name=kb["name"], description=kb.get("description", ""),
        document_count=len(docs), index_status=st, created_at=kb["created_at"],
    )  # fmt: skip
    return out, docs, counts


async def _get(db: DB, ctx: WorkspaceContext, kb_id: str) -> dict[str, Any]:
    kb = await db.knowledge_bases.find_one(
        {"_id": to_oid(kb_id, "Knowledge base"), "workspace_id": ctx.workspace_id, "deleted_at": None}
    )
    if not kb:
        raise not_found("Knowledge base not found")
    return kb


@router.get("", response_model=list[KbOut])
async def list_kbs(ctx: Viewer, db: DB):
    out = []
    async for kb in db.knowledge_bases.find({"workspace_id": ctx.workspace_id, "deleted_at": None}).sort("name", 1):
        out.append((await _out(db, ctx, kb))[0])
    return out


@router.post("", response_model=KbOut, status_code=status.HTTP_201_CREATED)
async def create_kb(body: KbIn, ctx: Editor, db: DB):
    now = utcnow()
    kb = {
        "workspace_id": ctx.workspace_id, "name": body.name.strip(), "description": body.description,
        "document_ids": [], "created_by": ctx.user_id, "deleted_at": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    try:
        kb["_id"] = (await db.knowledge_bases.insert_one(kb)).inserted_id
    except DuplicateKeyError:
        raise conflict("A knowledge base with that name exists", "duplicate_name") from None
    await audit.record(db, action="kb.create", actor_id=ctx.user_id, workspace_id=ctx.workspace_id, target={"kb": str(kb["_id"])})
    return (await _out(db, ctx, kb))[0]


@router.get("/{kb_id}", response_model=KbDetail)
async def get_kb(kb_id: str, ctx: Viewer, db: DB):
    out, docs, counts = await _out(db, ctx, await _get(db, ctx, kb_id))
    return KbDetail(
        **out.model_dump(), status_counts=counts,
        documents=[KbDocument(id=str(d["_id"]), title=d["title"], status=d["status"], error=d.get("error")) for d in docs],
    )  # fmt: skip


@router.patch("/{kb_id}", response_model=KbOut)
async def update_kb(kb_id: str, body: KbPatch, ctx: Editor, db: DB):
    kb = await _get(db, ctx, kb_id)
    patch: dict[str, Any] = {"updated_at": utcnow()}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.description is not None:
        patch["description"] = body.description
    try:
        await db.knowledge_bases.update_one({"_id": kb["_id"]}, {"$set": patch})
    except DuplicateKeyError:
        raise conflict("A knowledge base with that name exists", "duplicate_name") from None
    return (await _out(db, ctx, await _get(db, ctx, kb_id)))[0]


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kb(kb_id: str, ctx: Editor, db: DB) -> Response:
    kb = await _get(db, ctx, kb_id)
    await db.knowledge_bases.delete_one({"_id": kb["_id"]})  # documents themselves are untouched
    await audit.record(db, action="kb.delete", actor_id=ctx.user_id, workspace_id=ctx.workspace_id, target={"kb": kb_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{kb_id}/documents", response_model=KbOut)
async def add_documents(kb_id: str, body: AddDocsIn, ctx: Editor, db: DB):
    kb = await _get(db, ctx, kb_id)
    ids = [to_oid(i, "Document") for i in dict.fromkeys(body.document_ids)]
    found = await db.documents.count_documents({"_id": {"$in": ids}, "workspace_id": ctx.workspace_id, "deleted_at": None})
    if found != len(ids):
        raise bad_request("Unknown document", "invalid_document")
    await db.knowledge_bases.update_one({"_id": kb["_id"]}, {"$addToSet": {"document_ids": {"$each": ids}}, "$set": {"updated_at": utcnow()}})
    return (await _out(db, ctx, await _get(db, ctx, kb_id)))[0]


@router.delete("/{kb_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(kb_id: str, document_id: str, ctx: Editor, db: DB) -> Response:
    kb = await _get(db, ctx, kb_id)
    await db.knowledge_bases.update_one({"_id": kb["_id"]}, {"$pull": {"document_ids": to_oid(document_id, "Document")}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{kb_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex(kb_id: str, ctx: Editor, db: DB, queue: Queue, settings: Config):
    """Re-run the ingestion pipeline (re-chunk, re-embed, re-index) for every member document."""
    require_ai_consent(ctx, settings)
    kb = await _get(db, ctx, kb_id)
    queued = 0
    for d in await _docs(db, ctx, kb):
        if d["status"] in {"COMPLETED", "FAILED"}:
            await upload._queue_processing(db, queue, d["_id"], ctx.workspace_id, d["current_version_id"])
            queued += 1
    return {"queued": queued}


