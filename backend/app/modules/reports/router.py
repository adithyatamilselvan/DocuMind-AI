from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.errors import bad_request, conflict, not_found
from app.core.ids import PyId, to_oid
from app.modules.audit import service as audit
from app.modules.auth.deps import DB
from app.modules.documents.deps import Queue, Store
from app.modules.reports import service
from app.modules.storage_errors import not_available
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/reports", tags=["reports"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]

ReportType = Literal[
    "document_summary",
    "executive_summary",
    "multi_document",
    "findings",
    "research",
    "literature_review",
    "comparison",
]


class ReportOut(BaseModel):
    id: PyId
    type: str
    title: str
    status: str
    error: str | None
    formats: list[str]
    sections: list[dict[str, Any]] | None = None
    references: list[dict[str, Any]] | None = None
    created_at: datetime

    @classmethod
    def from_doc(cls, d: dict[str, Any], full: bool = False) -> "ReportOut":
        return cls(
            id=d["_id"], type=d["type"], title=d["title"], status=d["status"], error=d.get("error"),
            formats=[e["format"] for e in d.get("exports", [])], created_at=d["created_at"],
            sections=d.get("sections") if full else None, references=d.get("references") if full else None,
        )  # fmt: skip


class ReportIn(BaseModel):
    type: ReportType
    title: str | None = Field(None, max_length=200)
    document_ids: list[str] | None = Field(None, max_length=20)
    analysis_id: str | None = None
    comparison_id: str | None = None


async def _resolve(
    body: ReportIn, db: DB, ctx: WorkspaceContext
) -> tuple[dict[str, Any], list[Any], str]:
    t = body.type
    if t in {"document_summary", "executive_summary", "multi_document", "findings"}:
        ids = [to_oid(i, "Document") for i in dict.fromkeys(body.document_ids or [])]
        minimum = 2 if t in {"multi_document", "findings"} else 1
        if len(ids) < minimum or (t == "document_summary" and len(ids) != 1):
            raise bad_request(
                f"{service.TYPES[t]} needs {'one document' if t == 'document_summary' else f'at least {minimum} document(s)'}",
                "bad_sources",
            )
        found = await db.documents.count_documents(
            {"_id": {"$in": ids}, "workspace_id": ctx.workspace_id, "deleted_at": None}
        )
        if found != len(ids):
            raise not_found("Document not found")
        return {"document_ids": ids}, ids, service.TYPES[t]
    if t in {"research", "literature_review"}:
        a = await db.research_analyses.find_one(
            {"_id": to_oid(body.analysis_id or "", "Analysis"), "workspace_id": ctx.workspace_id}
        )
        want = "paper" if t == "research" else "synthesis"
        if not a or a["kind"] != want:
            raise not_found("Analysis not found")
        if a["status"] != "completed":
            raise conflict("The analysis has not completed", "not_ready")
        return {"analysis_id": a["_id"]}, a["document_ids"], a["title"]
    c = await db.document_comparisons.find_one(
        {"_id": to_oid(body.comparison_id or "", "Comparison"), "workspace_id": ctx.workspace_id}
    )
    if not c:
        raise not_found("Comparison not found")
    if c["status"] != "completed":
        raise conflict("The comparison has not completed", "not_ready")
    return {"comparison_id": c["_id"]}, c["document_ids"], c["title"]


@router.post("", response_model=ReportOut, status_code=status.HTTP_202_ACCEPTED)
async def create_report(body: ReportIn, ctx: Editor, db: DB, queue: Queue):
    source, doc_ids, default_title = await _resolve(body, db, ctx)
    rec, job = await service.create_report(
        db, workspace_id=ctx.workspace_id, user_id=ctx.user_id, rtype=body.type,
        title=body.title or default_title, source=source, source_document_ids=doc_ids,
    )  # fmt: skip
    await audit.record(
        db,
        action="report.create",
        actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        target={"report": str(rec["_id"]), "type": body.type},
    )
    await queue.enqueue(job["_id"])
    return ReportOut.from_doc(rec)


@router.get("", response_model=list[ReportOut])
async def list_reports(ctx: Viewer, db: DB):
    return [
        ReportOut.from_doc(r)
        async for r in db.reports.find({"workspace_id": ctx.workspace_id})
        .sort("created_at", -1)
        .limit(100)
    ]


async def _get(db: DB, ctx: WorkspaceContext, report_id: str) -> dict[str, Any]:
    r = await db.reports.find_one(
        {"_id": to_oid(report_id, "Report"), "workspace_id": ctx.workspace_id}
    )
    if not r:
        raise not_found("Report not found")
    return r


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: str, ctx: Viewer, db: DB):
    return ReportOut.from_doc(await _get(db, ctx, report_id), full=True)


@router.get("/{report_id}/download")
async def download_report(
    report_id: str, ctx: Viewer, db: DB, store: Store, format: Literal["pdf", "docx"] = "pdf"
):
    r = await _get(db, ctx, report_id)
    exp = next((e for e in r.get("exports", []) if e["format"] == format), None)
    if r["status"] != "completed" or not exp:
        raise conflict("The report is not ready", "not_ready")
    stream = store.stream(exp["storage_key"])
    first = await not_available(stream)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in r["title"]).strip() or "report"

    async def body():
        yield first
        async for chunk in stream:
            yield chunk

    return StreamingResponse(
        body(), media_type=service.MIME[format],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe)}.{format}",
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
            "Content-Length": str(exp["size_bytes"]),
        },
    )  # fmt: skip


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: str, ctx: Editor, db: DB, store: Store) -> Response:
    r = await _get(db, ctx, report_id)
    for e in r.get("exports", []):
        await store.delete(e["storage_key"])
    await db.reports.delete_one({"_id": r["_id"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
