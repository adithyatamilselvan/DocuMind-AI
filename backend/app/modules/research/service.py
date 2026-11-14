import json
import logging
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.ai import registry
from app.ai.errors import LLMError
from app.ai.prompts import insights as ip
from app.ai.prompts import research as rp
from app.ai.providers.llm import LLMProvider, LLMUsage
from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.extraction.models import ExtractedDocument
from app.modules.ingestion.errors import PermanentError, RetryableError
from app.modules.ingestion.jobs_util import ai_unavailable_reason, load_extracted_doc, set_job
from app.modules.insights.evidence import PageIndex
from app.modules.insights.schemas import Finding, SectionNotes
from app.modules.insights.service import render_pages, windows
from app.modules.research.schemas import (
    SCHEMA_VERSION,
    Gap,
    PaperAnalysis,
    PaperItem,
    Synthesis,
)  # fmt: skip
from app.modules.usage.service import record_usage

log = logging.getLogger("documind.research")


async def read_document(
    llm: LLMProvider,
    settings: Settings,
    title: str,
    doc: ExtractedDocument,
    system: str,
    schema: type,
    max_tokens: int,
) -> tuple[Any, list[LLMUsage]]:
    """Single call for short documents; map (SectionNotes) then reduce for long ones."""
    parts = render_pages(doc)
    body = "\n\n".join(t for _, t in parts)
    usages: list[LLMUsage] = []
    if len(body) <= settings.insights_max_direct_chars:
        user = ip.render_document(title, body)
    else:
        notes = []
        for i, w in enumerate(windows(parts, settings.insights_window_chars), start=1):
            sn, u = await llm.structured(
                ip.SECTION_SYSTEM, [{"role": "user", "content": ip.render_document(f"{title} (part {i})", w)}],
                SectionNotes, max_tokens=3000,
            )  # fmt: skip
            usages.append(u)
            notes.append(
                json.dumps({"part": i, **sn.model_dump(exclude_none=True)}, ensure_ascii=False)
            )
        user = ip.REDUCE_NOTE + "\n\n" + ip.render_document(title, "\n".join(notes))
    result, u = await llm.structured(
        system, [{"role": "user", "content": user}], schema, max_tokens=max_tokens
    )
    return result, [*usages, u]


def verify_paper(a: PaperAnalysis, doc: ExtractedDocument) -> tuple[dict[str, Any], dict[str, int]]:
    idx = PageIndex.from_document(doc)
    r = a.model_copy(deep=True)
    for fld in (
        "research_questions",
        "hypotheses",
        "datasets",
        "results",
        "conclusions",
        "limitations",
        "future_work",
    ):
        setattr(r, fld, idx.verify_all(getattr(r, fld)))
    for fld in ("objective", "sample_size"):
        f: Finding | None = getattr(r, fld)
        if f is not None:
            setattr(r, fld, idx.verify(f))
    r.methodology.evidence = idx.verify_all(r.methodology.evidence)
    gaps = []
    for g in r.potential_gaps:
        gaps.append(Gap(text=g.text, rationale=g.rationale, evidence=idx.verify_all(g.evidence)))
    r.potential_gaps = gaps
    out = r.model_dump()
    out["potential_gaps"] = [{**g, "ai_inferred": True} for g in out["potential_gaps"]]
    return out, {"dropped_quotes": idx.dropped_quotes, "dropped_pages": idx.dropped_pages}


def verify_synthesis(
    s: Synthesis, indexes: dict[int, PageIndex], papers: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, int]]:
    n = len(papers)
    stats = {"dropped_items": 0, "dropped_quotes": 0}

    def fix(item: PaperItem) -> PaperItem | None:
        if not 1 <= item.paper <= n:
            stats["dropped_items"] += 1
            return None
        idx = indexes[item.paper]
        before = idx.dropped_quotes
        f = idx.verify(Finding(text=item.text, page=item.page, quote=item.quote))
        stats["dropped_quotes"] += idx.dropped_quotes - before
        return PaperItem(text=f.text, paper=item.paper, page=f.page, quote=f.quote)

    themes = []
    for t in s.themes:
        items = [x for x in (fix(i) for i in t.items) if x]
        themes.append(
            {"title": t.title, "summary": t.summary, "items": [i.model_dump() for i in items]}
        )
    contradictions = []
    for c in s.contradictions:
        pos = [x for x in (fix(i) for i in c.positions) if x]
        if len({p.paper for p in pos}) >= 2:  # a contradiction needs at least two different papers
            contradictions.append(
                {
                    "topic": c.topic,
                    "explanation": c.explanation,
                    "positions": [p.model_dump() for p in pos],
                }
            )
        else:
            stats["dropped_items"] += 1
    out = {
        "overview": s.overview, "themes": themes,
        "comparison_table": [r.model_dump() for r in s.comparison_table if 1 <= r.paper <= n],
        "contradictions": contradictions,
        "trends": [i.model_dump() for i in (fix(t) for t in s.trends) if i],
        "research_gaps": [
            {**g.model_dump(), "papers": [p for p in g.papers if 1 <= p <= n], "ai_inferred": True}
            for g in s.research_gaps
        ],
        "papers": papers,
    }  # fmt: skip
    return out, stats


async def _usage(
    db: AsyncDatabase,
    ws: ObjectId,
    user: ObjectId | None,
    llm: LLMProvider,
    usages: list[LLMUsage],
    kind: str,
) -> None:
    for u in usages:
        await record_usage(
            db, workspace_id=ws, user_id=user, kind=kind, provider=llm.name, model=llm.model,
            tokens_in=u.input_tokens, tokens_out=u.output_tokens, latency_ms=u.latency_ms,
        )  # fmt: skip


async def create_record(
    db: AsyncDatabase, *, workspace_id: ObjectId, user_id: ObjectId, kind: str, title: str,
    documents: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:  # fmt: skip
    now = utcnow()
    rec = {
        "workspace_id": workspace_id, "kind": kind, "title": title, "status": "pending", "error": None,
        "document_ids": [d["_id"] for d in documents], "version_ids": [d["current_version_id"] for d in documents],
        "result": None, "verification": None, "created_by": user_id, "created_at": now, "updated_at": now,
    }  # fmt: skip
    rec["_id"] = (await db.research_analyses.insert_one(rec)).inserted_id
    job = {
        "workspace_id": workspace_id, "type": "research", "analysis_id": rec["_id"], "state": "queued",
        "attempts": 0, "stages": {}, "progress": 0.0, "error": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    job["_id"] = (await db.processing_jobs.insert_one(job)).inserted_id
    return rec, job


async def _paper_for(
    db: AsyncDatabase, llm: LLMProvider, settings: Settings, store: Any, document: dict[str, Any],
    version: dict[str, Any], user_id: ObjectId | None, persist: bool = True,
) -> tuple[dict[str, Any], ExtractedDocument, dict[str, int] | None]:  # fmt: skip
    """Paper analysis for one document version, reusing a completed one. `persist=False` leaves
    storing the result to the caller (used when the analysis record already exists)."""
    doc = await load_extracted_doc(store, version)
    cached = await db.research_analyses.find_one(
        {
            "kind": "paper",
            "version_ids": [version["_id"]],
            "status": "completed",
            "workspace_id": document["workspace_id"],
        }
    )
    if cached:
        return cached["result"], doc, cached.get("verification")
    result, usages = await read_document(
        llm, settings, document["title"], doc, rp.PAPER_SYSTEM, PaperAnalysis, 6000
    )
    await _usage(db, document["workspace_id"], user_id, llm, usages, "research")
    payload, ver = verify_paper(result, doc)
    if not persist:
        return payload, doc, ver
    now = utcnow()
    await db.research_analyses.insert_one(
        {
            "workspace_id": document["workspace_id"], "kind": "paper", "title": document["title"],
            "status": "completed", "error": None, "document_ids": [document["_id"]], "version_ids": [version["_id"]],
            "result": payload, "verification": ver, "model": llm.model, "prompt_version": rp.PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION, "created_by": user_id, "created_at": now, "updated_at": now,
        }
    )  # fmt: skip
    return payload, doc, ver


async def run_research_job(
    db: AsyncDatabase, settings: Settings, store: Any, job_id: ObjectId
) -> None:
    job = await db.processing_jobs.find_one({"_id": job_id})
    if not job or job["state"] in {"completed", "failed"}:
        return
    rec = await db.research_analyses.find_one({"_id": job["analysis_id"]})
    if not rec:
        return await set_job(db, job_id, "failed", error="gone")
    ws = await db.workspaces.find_one({"_id": rec["workspace_id"]})
    if reason := ai_unavailable_reason(settings, ws):
        await db.research_analyses.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "unavailable", "error": reason, "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "completed")
    attempts = job["attempts"] + 1
    await set_job(db, job_id, "running", attempts=attempts)
    await db.research_analyses.update_one(
        {"_id": rec["_id"]}, {"$set": {"status": "running", "error": None}}
    )
    llm = registry.get_llm(settings)
    try:
        docs = [
            d
            async for d in db.documents.find(
                {
                    "_id": {"$in": rec["document_ids"]},
                    "workspace_id": rec["workspace_id"],
                    "deleted_at": None,
                }
            )
        ]
        by_id = {d["_id"]: d for d in docs}
        ordered = [by_id[i] for i in rec["document_ids"] if i in by_id]
        if len(ordered) != len(rec["document_ids"]):
            raise PermanentError("One of the documents no longer exists")
        versions = {
            v["_id"]: v
            async for v in db.document_versions.find({"_id": {"$in": rec["version_ids"]}})
        }
        if rec["kind"] == "paper":
            d = ordered[0]
            result, _doc, ver = await _paper_for(
                db,
                llm,
                settings,
                store,
                d,
                versions[d["current_version_id"]],
                rec.get("created_by"),
                persist=False,
            )
        else:
            papers_meta, analyses, indexes = [], [], {}
            for i, d in enumerate(ordered, start=1):
                payload, doc, _ = await _paper_for(
                    db,
                    llm,
                    settings,
                    store,
                    d,
                    versions[d["current_version_id"]],
                    rec.get("created_by"),
                )
                papers_meta.append({"index": i, "document_id": str(d["_id"]), "title": d["title"]})
                analyses.append({"paper": i, "title": d["title"], "analysis": payload})
                indexes[i] = PageIndex.from_document(doc)
            body = "\n".join(json.dumps(a, ensure_ascii=False) for a in analyses)
            synth, usages = await llm.structured(
                rp.SYNTH_SYSTEM, [{"role": "user", "content": ip.render_document(rec["title"], body)}], Synthesis, max_tokens=8000
            )  # fmt: skip
            await _usage(db, rec["workspace_id"], rec.get("created_by"), llm, [usages], "research")
            result, ver = verify_synthesis(synth, indexes, papers_meta)
    except LLMError as e:
        if e.retryable and attempts < settings.job_max_attempts:
            await set_job(db, job_id, "retrying")
            raise RetryableError(e.message) from e
        await db.research_analyses.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "failed", "error": e.message, "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "failed", error=e.message)
    except PermanentError as e:
        await db.research_analyses.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "failed", "error": str(e), "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "failed", error=str(e))
    await db.research_analyses.update_one(
        {"_id": rec["_id"]},
        {"$set": {"status": "completed", "result": result, "verification": ver, "model": llm.model,
                  "prompt_version": rp.PROMPT_VERSION, "schema_version": SCHEMA_VERSION, "updated_at": utcnow()}},
    )  # fmt: skip
    await set_job(db, job_id, "completed", progress=1.0)
