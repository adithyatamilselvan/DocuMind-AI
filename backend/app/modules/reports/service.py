import asyncio
import logging
import os
import tempfile
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.ingestion.errors import PermanentError
from app.modules.ingestion.jobs_util import set_job
from app.modules.reports import builders as b
from app.modules.reports import render

log = logging.getLogger("documind.reports")
TYPES = {
    "document_summary": "Document summary",
    "executive_summary": "Executive summary",
    "multi_document": "Multi-document analysis",
    "findings": "Findings report",
    "research": "Research report",
    "literature_review": "Literature review",
    "comparison": "Comparison report",
}
DISCLAIMER = (
    "This report was generated with AI assistance from the cited documents. Quotes and page numbers were checked "
    "against the extracted document text; verify important details in the source documents."
)
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def storage_key(workspace_id: ObjectId, report_id: ObjectId, fmt: str) -> str:
    return f"workspaces/{workspace_id}/reports/{report_id}/report.{fmt}"


async def _insights(db: AsyncDatabase, doc: dict[str, Any]) -> dict[str, Any]:
    rec = await db.document_insights.find_one(
        {
            "document_version_id": doc["current_version_id"],
            "kind": "overview",
            "status": "completed",
        }
    )
    if not rec:
        raise PermanentError(
            f'Insights for "{doc["title"]}" are not available; generate them first'
        )
    return rec


async def _optional_insights(db: AsyncDatabase, doc: dict[str, Any]) -> dict[str, Any] | None:
    return await db.document_insights.find_one(
        {"document_version_id": doc["current_version_id"], "kind": "overview", "status": "completed"}
    )


async def build_content(
    db: AsyncDatabase, rec: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    refs = b.Refs()
    ws, src = rec["workspace_id"], rec["source"]
    rtype = rec["type"]

    async def docs(ids: list[ObjectId]) -> list[dict[str, Any]]:
        found = {
            d["_id"]: d
            async for d in db.documents.find(
                {"_id": {"$in": ids}, "workspace_id": ws, "deleted_at": None}
            )
        }
        if len(found) != len(ids):
            raise PermanentError("A source document no longer exists")
        return [found[i] for i in ids]

    if rtype == "document_summary":
        (d,) = await docs(src["document_ids"])
        return (
            b.from_insights(d, await _insights(db, d), refs),
            refs.items,
            f"Source document: {d['title']}",
        )
    if rtype in {"executive_summary", "multi_document", "findings"}:
        ds = await docs(src["document_ids"])
        pairs = [(d, await _insights(db, d)) for d in ds]
        sections = b.from_multi_insights(pairs, refs, executive_only=rtype == "executive_summary")
        return sections, refs.items, "Sources: " + ", ".join(d["title"] for d in ds)
    if rtype in {"research", "literature_review"}:
        analysis = await db.research_analyses.find_one(
            {"_id": src["analysis_id"], "workspace_id": ws, "status": "completed"}
        )
        if not analysis:
            raise PermanentError("The research analysis is no longer available")
        if rtype == "research":
            (d,) = await docs(analysis["document_ids"])
            ins = await _optional_insights(db, d)
            return b.from_paper(d, analysis, refs, ins), refs.items, f"Source document: {d['title']}"
        ds = await docs(analysis["document_ids"])
        return (
            b.from_synthesis(analysis, refs),
            refs.items,
            "Papers: " + ", ".join(d["title"] for d in ds),
        )
    comp = await db.document_comparisons.find_one(
        {"_id": src["comparison_id"], "workspace_id": ws, "status": "completed"}
    )
    if not comp:
        raise PermanentError("The comparison is no longer available")
    ds = await docs(comp["document_ids"])
    return (
        b.from_comparison(comp, refs),
        refs.items,
        "Compared: " + ", ".join(d["title"] for d in ds),
    )


async def run_report_job(
    db: AsyncDatabase, settings: Settings, store: Any, job_id: ObjectId
) -> None:
    job = await db.processing_jobs.find_one({"_id": job_id})
    if not job or job["state"] in {"completed", "failed"}:
        return
    rec = await db.reports.find_one({"_id": job["report_id"]})
    if not rec:
        return await set_job(db, job_id, "failed", error="gone")
    await set_job(db, job_id, "running", attempts=job["attempts"] + 1)
    await db.reports.update_one({"_id": rec["_id"]}, {"$set": {"status": "running", "error": None}})
    try:
        sections, refs, subtitle = await build_content(db, rec)
        if not sections:
            raise PermanentError("There is no content to put in this report")
        now = utcnow()
        exports = []
        for fmt, fn in (("pdf", render.to_pdf), ("docx", render.to_docx)):
            data = await asyncio.to_thread(
                fn, rec["title"], now, subtitle, sections, refs, DISCLAIMER
            )
            fd, path = tempfile.mkstemp(prefix="documind-report-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                key = storage_key(rec["workspace_id"], rec["_id"], fmt)
                await store.put_file(key, path, MIME[fmt])
            finally:
                os.unlink(path)
            exports.append({"format": fmt, "storage_key": key, "size_bytes": len(data)})
    except PermanentError as e:
        await db.reports.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "failed", "error": str(e), "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "failed", error=str(e))
    await db.reports.update_one(
        {"_id": rec["_id"]},
        {"$set": {"status": "completed", "sections": sections, "references": refs, "subtitle": subtitle, "exports": exports, "updated_at": utcnow()}},
    )  # fmt: skip
    await set_job(db, job_id, "completed", progress=1.0)


async def create_report(
    db: AsyncDatabase, *, workspace_id: ObjectId, user_id: ObjectId, rtype: str, title: str,
    source: dict[str, Any], source_document_ids: list[ObjectId],
) -> tuple[dict[str, Any], dict[str, Any]]:  # fmt: skip
    now = utcnow()
    rec = {
        "workspace_id": workspace_id, "type": rtype, "title": title, "status": "pending", "error": None,
        "source": source, "source_document_ids": source_document_ids, "sections": None, "references": None,
        "exports": [], "created_by": user_id, "created_at": now, "updated_at": now,
    }  # fmt: skip
    rec["_id"] = (await db.reports.insert_one(rec)).inserted_id
    job = {
        "workspace_id": workspace_id, "type": "report", "report_id": rec["_id"], "state": "queued", "attempts": 0,
        "stages": {}, "progress": 0.0, "error": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    job["_id"] = (await db.processing_jobs.insert_one(job)).inserted_id
    return rec, job
