from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from pymongo import DESCENDING

from app.core.config import Settings, get_settings
from app.core.errors import conflict
from app.modules.auth.deps import DB
from app.modules.documents import service as documents
from app.modules.documents.deps import Queue
from app.modules.documents.transfer_router import require_ai_consent
from app.modules.insights import service
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["insights"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]
Config = Annotated[Settings, Depends(get_settings)]


class InsightsOut(BaseModel):
    status: str  # none | pending | running | completed | failed | unavailable
    error: str | None = None
    payload: dict[str, Any] | None = None
    structure: dict[str, Any] | None = None
    model: str | None = None
    prompt_version: str | None = None
    verification: dict[str, int] | None = None
    generated_at: datetime | None = None


@router.get("/documents/{document_id}/insights", response_model=InsightsOut)
async def get_insights(document_id: str, ctx: Viewer, db: DB, settings: Config):
    doc = await documents.get_document(db, ctx.workspace_id, document_id)
    rec = await db.document_insights.find_one(
        {"document_version_id": doc["current_version_id"], "kind": service.KIND}
    )
    if not rec:
        if doc["status"] != "COMPLETED":
            return InsightsOut(status="none")
        reason = service.unavailable_reason(settings, ctx.workspace)
        return InsightsOut(status="unavailable" if reason else "none", error=reason)
    return InsightsOut(
        status=rec["status"], error=rec.get("error"), payload=rec.get("payload"),
        structure=rec.get("structure"), model=rec.get("model"), prompt_version=rec.get("prompt_version"),
        verification=rec.get("verification"), generated_at=rec.get("updated_at"),
    )  # fmt: skip


@router.post("/documents/{document_id}/insights", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_insights(
    document_id: str, ctx: Editor, db: DB, settings: Config, queue: Queue
):
    require_ai_consent(ctx, settings)
    doc = await documents.get_document(db, ctx.workspace_id, document_id)
    if doc["status"] != "COMPLETED":
        raise conflict("The document must finish processing first", "not_ready")
    running = await db.document_insights.find_one(
        {
            "document_version_id": doc["current_version_id"],
            "kind": service.KIND,
            "status": {"$in": ["pending", "running"]},
        }
    )
    if running:
        raise conflict("Insights are already being generated", "in_progress")
    job = await service.create_insights_job(
        db, ctx.workspace_id, doc["_id"], doc["current_version_id"]
    )
    await queue.enqueue(job["_id"])
    return {"status": "pending"}


class InsightSummary(BaseModel):
    document_id: str
    title: str
    category: str | None
    document_type: str | None
    summary: str
    topics: list[str]
    generated_at: datetime


@router.get("/insights", response_model=list[InsightSummary])
async def list_insights(ctx: Viewer, db: DB, category: str | None = None, limit: int = 50):
    """Overview of completed insights for the current version of every live document."""
    limit = max(1, min(limit, 200))
    docs = {
        d["_id"]: d
        async for d in db.documents.find(
            {"workspace_id": ctx.workspace_id, "deleted_at": None, "status": "COMPLETED"}
        )
    }
    out: list[InsightSummary] = []
    cursor = db.document_insights.find(
        {"workspace_id": ctx.workspace_id, "kind": service.KIND, "status": "completed"}
    ).sort("updated_at", DESCENDING)
    async for rec in cursor:
        d = docs.get(rec["document_id"])
        if not d or d["current_version_id"] != rec["document_version_id"]:
            continue
        cls = rec["payload"].get("classification") or {}
        cat = d.get("category") or cls.get("category")
        if category and cat != category:
            continue
        out.append(InsightSummary(
            document_id=str(d["_id"]), title=d["title"], category=cat, document_type=cls.get("document_type"),
            summary=rec["payload"]["executive_summary"] or rec["payload"]["summary"],
            topics=rec["payload"].get("topics", [])[:6], generated_at=rec["updated_at"],
        ))  # fmt: skip
        if len(out) >= limit:
            break
    return out


@router.get("/suggestions", response_model=list[str])
async def suggested_questions(ctx: Viewer, db: DB):
    """Starter questions taken from the insights of the most recently analysed documents."""
    docs = {
        d["_id"]: d["current_version_id"]
        async for d in db.documents.find(
            {"workspace_id": ctx.workspace_id, "deleted_at": None, "status": "COMPLETED"},
            {"current_version_id": 1},
        )
    }
    out: list[str] = []
    async for rec in (
        db.document_insights.find(
            {"workspace_id": ctx.workspace_id, "kind": service.KIND, "status": "completed"}
        )
        .sort("updated_at", DESCENDING)
        .limit(20)
    ):
        if docs.get(rec["document_id"]) != rec["document_version_id"]:
            continue
        for q in rec["payload"].get("suggested_questions", [])[:2]:
            if q not in out:
                out.append(q)
        if len(out) >= 6:
            break
    return out[:6]
