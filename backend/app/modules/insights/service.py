import json
import logging
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.ai import registry
from app.ai.errors import LLMError
from app.ai.prompts import insights as prompts
from app.ai.providers.llm import LLMProvider, LLMUsage
from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.extraction.models import ExtractedDocument
from app.modules.ingestion.errors import PermanentError, RetryableError
from app.modules.insights.evidence import PageIndex
from app.modules.insights.schemas import SCHEMA_VERSION, DocumentInsights, SectionNotes
from app.modules.insights.structure import build_structure
from app.modules.usage.service import record_usage

log = logging.getLogger("documind.insights")
KIND = "overview"


def page_label(doc: ExtractedDocument) -> str:
    return "Page" if doc.page_basis == "physical" else "Section"


def render_pages(doc: ExtractedDocument) -> list[tuple[int, str]]:
    label = page_label(doc)
    return [(p.number, f"[{label} {p.number}]\n{p.text}") for p in doc.pages if p.text.strip()]


def windows(parts: list[tuple[int, str]], limit: int) -> list[str]:
    """Group consecutive pages into windows of at most `limit` characters (a page is never split
    unless it alone exceeds the limit)."""
    out: list[str] = []
    cur = ""
    for _, text in parts:
        for piece in [text[i : i + limit] for i in range(0, len(text), limit)] or [""]:
            if cur and len(cur) + len(piece) > limit:
                out.append(cur)
                cur = ""
            cur += ("\n\n" if cur else "") + piece
    if cur:
        out.append(cur)
    return out


async def generate(
    llm: LLMProvider, settings: Settings, title: str, doc: ExtractedDocument
) -> tuple[DocumentInsights, list[LLMUsage]]:
    parts = render_pages(doc)
    body = "\n\n".join(t for _, t in parts)
    usages: list[LLMUsage] = []
    if len(body) <= settings.insights_max_direct_chars:
        user = prompts.render_document(title, body)
    else:
        notes: list[str] = []
        for i, window in enumerate(windows(parts, settings.insights_window_chars), start=1):
            sn, u = await llm.structured(
                prompts.SECTION_SYSTEM,
                [{"role": "user", "content": prompts.render_document(f"{title} (part {i})", window)}],
                SectionNotes, max_tokens=3000,
            )  # fmt: skip
            usages.append(u)
            notes.append(
                json.dumps({"part": i, **sn.model_dump(exclude_none=True)}, ensure_ascii=False)
            )
        user = prompts.REDUCE_NOTE + "\n\n" + prompts.render_document(title, "\n".join(notes))
    result, u = await llm.structured(
        prompts.SYSTEM, [{"role": "user", "content": user}], DocumentInsights, max_tokens=6000
    )
    usages.append(u)
    return result, usages


def verified_payload(
    result: DocumentInsights, doc: ExtractedDocument
) -> tuple[dict[str, Any], dict[str, int]]:
    """Check every quote/page against the real text; unverifiable evidence is removed, not shown."""
    idx = PageIndex.from_document(doc)
    r = result.model_copy(deep=True)
    for fld in ("key_findings", "key_facts", "main_arguments", "conclusions", "limitations"):
        setattr(r, fld, idx.verify_all(getattr(r, fld)))
    r.important_dates = idx.verify_dates(r.important_dates)
    return r.model_dump(), {
        "dropped_quotes": idx.dropped_quotes,
        "dropped_pages": idx.dropped_pages,
    }


async def set_status(
    db: AsyncDatabase, document: dict[str, Any], version_id: ObjectId, status: str, **fields: Any
) -> None:
    await db.document_insights.update_one(
        {"document_version_id": version_id, "kind": KIND},
        {
            "$set": {"status": status, "updated_at": utcnow(), **fields},
            "$setOnInsert": {
                "workspace_id": document["workspace_id"], "document_id": document["_id"],
                "kind": KIND, "created_at": utcnow(),
            },
        },
        upsert=True,
    )  # fmt: skip


def unavailable_reason(settings: Settings, workspace: dict[str, Any] | None) -> str | None:
    if not settings.insights_enabled:
        return "Document insights are disabled on this server."
    if not settings.llm_configured:
        return "AI insights are not configured on this server (missing LLM API key)."
    if settings.ai_external and not (
        workspace and workspace.get("settings", {}).get("ai_processing_consent")
    ):
        return "External AI processing is not enabled for this workspace."
    return None


async def run_insights_job(
    db: AsyncDatabase, settings: Settings, store: Any, job_id: ObjectId
) -> None:
    """Raises RetryableError for transient failures (the queue re-runs the job)."""
    from app.modules.ingestion.stages import extracted_key  # local import: avoids a cycle

    job = await db.processing_jobs.find_one({"_id": job_id})
    if not job or job["state"] in {"completed", "failed"}:
        return
    document = await db.documents.find_one({"_id": job["document_id"], "deleted_at": None})
    version = await db.document_versions.find_one({"_id": job["document_version_id"]})
    if not document or not version:
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "failed", "error": "gone"}}
        )
        return
    ws = await db.workspaces.find_one({"_id": document["workspace_id"]})
    if reason := unavailable_reason(settings, ws):
        await set_status(db, document, version["_id"], "unavailable", error=reason)
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "completed", "updated_at": utcnow()}}
        )
        return

    attempts = job["attempts"] + 1
    await db.processing_jobs.update_one(
        {"_id": job_id}, {"$set": {"state": "running", "attempts": attempts}}
    )
    await set_status(db, document, version["_id"], "running", error=None)
    try:
        raw = await store.get_bytes(extracted_key(version["storage_key"]))
        doc = ExtractedDocument.from_json(json.loads(raw))
        llm = registry.get_llm(settings)
        result, usages = await generate(llm, settings, document["title"], doc)
        payload, verification = verified_payload(result, doc)
        for u in usages:
            await record_usage(
                db, workspace_id=document["workspace_id"], user_id=document.get("owner_id"), kind="insight",
                provider=llm.name, model=llm.model, tokens_in=u.input_tokens, tokens_out=u.output_tokens,
                latency_ms=u.latency_ms, meta={"document_id": str(document["_id"]), "prompt_version": prompts.PROMPT_VERSION},
            )  # fmt: skip
    except LLMError as e:
        if e.retryable and attempts < settings.job_max_attempts:
            await db.processing_jobs.update_one({"_id": job_id}, {"$set": {"state": "retrying"}})
            raise RetryableError(e.message) from e
        await set_status(db, document, version["_id"], "failed", error=e.message)
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "failed", "error": e.message}}
        )
        return
    except PermanentError as e:
        await set_status(db, document, version["_id"], "failed", error=str(e))
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "failed", "error": str(e)}}
        )
        return

    await set_status(
        db, document, version["_id"], "completed", payload=payload, structure=build_structure(doc),
        model=llm.model, provider=llm.name, prompt_version=prompts.PROMPT_VERSION,
        schema_version=SCHEMA_VERSION, verification=verification, error=None,
    )  # fmt: skip
    cat = (payload.get("classification") or {}).get("category")
    if cat and not document.get("category"):
        await db.documents.update_one(
            {"_id": document["_id"], "category": None},
            {"$set": {"category": cat, "category_source": "ai"}},
        )
    await db.processing_jobs.update_one(
        {"_id": job_id}, {"$set": {"state": "completed", "updated_at": utcnow()}}
    )


async def create_insights_job(
    db: AsyncDatabase, workspace_id: ObjectId, document_id: ObjectId, version_id: ObjectId
) -> dict[str, Any]:
    now = utcnow()
    job = {
        "workspace_id": workspace_id, "document_id": document_id, "document_version_id": version_id,
        "type": "insights", "state": "queued", "attempts": 0, "stages": {}, "progress": 0.0,
        "error": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    job["_id"] = (await db.processing_jobs.insert_one(job)).inserted_id
    await db.document_insights.update_one(
        {"document_version_id": version_id, "kind": KIND},
        {"$set": {"status": "pending", "updated_at": now, "error": None},
         "$setOnInsert": {"workspace_id": workspace_id, "document_id": document_id, "kind": KIND, "created_at": now}},
        upsert=True,
    )  # fmt: skip
    return job
