from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.ids import PyId, to_oid
from app.modules.audit import service as audit
from app.modules.auth.deps import DB
from app.modules.documents.deps import Queue
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.research import service
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/research", tags=["research"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]
Config = Annotated[Settings, Depends(get_settings)]


class AnalysisOut(BaseModel):
    id: PyId
    kind: str
    title: str
    status: str
    error: str | None
    document_ids: list[PyId]
    result: dict[str, Any] | None
    verification: dict[str, int] | None
    model: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any], with_result: bool = True) -> "AnalysisOut":
        return cls(
            id=d["_id"], kind=d["kind"], title=d["title"], status=d["status"], error=d.get("error"),
            document_ids=d["document_ids"], result=d.get("result") if with_result else None,
            verification=d.get("verification"), model=d.get("model"),
            created_at=d["created_at"], updated_at=d["updated_at"],
        )  # fmt: skip


class PaperIn(BaseModel):
    document_id: str


class SynthesisIn(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=10)
    title: str | None = Field(None, max_length=200)


async def _docs(db: DB, ctx: WorkspaceContext, ids: list[str]) -> list[dict[str, Any]]:
    oids = [to_oid(i, "Document") for i in dict.fromkeys(ids)]
    found = {
        d["_id"]: d
        async for d in db.documents.find(
            {"_id": {"$in": oids}, "workspace_id": ctx.workspace_id, "deleted_at": None}
        )
    }
    if len(found) != len(oids):
        raise not_found("Document not found")
    docs = [found[i] for i in oids]
    if any(d["status"] != "COMPLETED" for d in docs):
        raise conflict("All documents must finish processing first", "not_ready")
    return docs


async def _start(
    db: DB,
    ctx: WorkspaceContext,
    queue: Queue,
    settings: Settings,
    kind: str,
    title: str,
    docs: list[dict[str, Any]],
) -> AnalysisOut:
    require_ai_consent(ctx, settings)
    rec, job = await service.create_record(
        db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        kind=kind,
        title=title,
        documents=docs,
    )
    await audit.record(
        db,
        action=f"research.{kind}",
        actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        target={"analysis": str(rec["_id"])},
    )
    await queue.enqueue(job["_id"])
    return AnalysisOut.from_doc(rec)


@router.post("/papers", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED)
async def analyse_paper(body: PaperIn, ctx: Editor, db: DB, queue: Queue, settings: Config):
    docs = await _docs(db, ctx, [body.document_id])
    return await _start(db, ctx, queue, settings, "paper", docs[0]["title"], docs)


@router.post("/synthesis", response_model=AnalysisOut, status_code=status.HTTP_202_ACCEPTED)
async def synthesise(body: SynthesisIn, ctx: Editor, db: DB, queue: Queue, settings: Config):
    docs = await _docs(db, ctx, body.document_ids)
    if len(docs) < 2:
        raise bad_request("Select at least two different documents", "too_few_documents")
    return await _start(
        db,
        ctx,
        queue,
        settings,
        "synthesis",
        body.title or f"Literature review ({len(docs)} papers)",
        docs,
    )


@router.get("", response_model=list[AnalysisOut])
async def list_analyses(ctx: Viewer, db: DB, kind: str | None = None):
    q: dict[str, Any] = {"workspace_id": ctx.workspace_id}
    if kind:
        q["kind"] = kind
    return [
        AnalysisOut.from_doc(d, with_result=False)
        async for d in db.research_analyses.find(q).sort("created_at", -1).limit(100)
    ]


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(analysis_id: str, ctx: Viewer, db: DB):
    d = await db.research_analyses.find_one(
        {"_id": to_oid(analysis_id, "Analysis"), "workspace_id": ctx.workspace_id}
    )
    if not d:
        raise not_found("Analysis not found")
    return AnalysisOut.from_doc(d)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: str, ctx: Editor, db: DB) -> Response:
    res = await db.research_analyses.delete_one(
        {"_id": to_oid(analysis_id, "Analysis"), "workspace_id": ctx.workspace_id}
    )
    if not res.deleted_count:
        raise not_found("Analysis not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
