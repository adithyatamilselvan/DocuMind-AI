import difflib
import logging
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.ai import registry
from app.ai.errors import LLMError
from app.ai.prompts import comparison as cp
from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.comparison.schemas import ComparisonResult, VersionSummary
from app.modules.extraction.models import ExtractedDocument
from app.modules.ingestion.errors import PermanentError, RetryableError
from app.modules.ingestion.jobs_util import ai_unavailable_reason, load_extracted_doc, set_job
from app.modules.retrieval.service import retrieve
from app.modules.usage.service import record_usage
from app.modules.vector_search.base import Scope
from app.modules.vector_search.factory import build_vector_store

log = logging.getLogger("documind.comparison")
DEFAULT_ASPECTS = {
    "Overall topic and purpose": "main topic purpose objective scope",
    "Methodology": "method approach procedure design how it was done",
    "Results": "results findings outcomes numbers data",
    "Conclusions": "conclusions recommendations implications summary",
}
PASSAGES_PER_DOC = 3


# ---------- deterministic version diff ----------


def _paragraphs(doc: ExtractedDocument) -> list[tuple[int, str]]:
    return [(p.number, b.text) for p in doc.pages for b in p.blocks if b.text.strip()]


def diff_versions(old: ExtractedDocument, new: ExtractedDocument) -> dict[str, Any]:
    """Paragraph-level diff: added, removed and changed (similar) paragraphs with page numbers."""
    a, b = _paragraphs(old), _paragraphs(new)
    sm = difflib.SequenceMatcher(a=[t for _, t in a], b=[t for _, t in b], autojunk=False)
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        old_chunk, new_chunk = a[i1:i2], b[j1:j2]
        if op == "replace":
            used: set[int] = set()
            for pa, ta in old_chunk:
                best, score = None, 0.0
                for k, (_pb, tb) in enumerate(new_chunk):
                    if k in used:
                        continue
                    r = difflib.SequenceMatcher(a=ta, b=tb).ratio()
                    if r > score:
                        best, score = k, r
                if best is not None and score >= 0.5:
                    used.add(best)
                    changed.append(
                        {
                            "before": ta,
                            "after": new_chunk[best][1],
                            "old_page": pa,
                            "new_page": new_chunk[best][0],
                            "similarity": round(score, 2),
                        }
                    )
                else:
                    removed.append({"page": pa, "text": ta})
            added += [
                {"page": pb, "text": tb} for k, (pb, tb) in enumerate(new_chunk) if k not in used
            ]
        elif op == "delete":
            removed += [{"page": p, "text": t} for p, t in old_chunk]
        elif op == "insert":
            added += [{"page": p, "text": t} for p, t in new_chunk]
    return {
        "added": added[:200], "removed": removed[:200], "changed": changed[:200],
        "stats": {"added": len(added), "removed": len(removed), "changed": len(changed),
                  "old_paragraphs": len(a), "new_paragraphs": len(b)},
    }  # fmt: skip


# ---------- grounded document comparison ----------


async def gather_evidence(
    db: AsyncDatabase,
    settings: Settings,
    workspace_id: ObjectId,
    docs: list[dict[str, Any]],
    aspects: dict[str, str],
) -> tuple[dict[str, dict[int, list[dict[str, Any]]]], dict[str, Any]]:
    store = build_vector_store(settings)
    embedder, reranker = registry.get_embedder(settings), registry.get_reranker_for(settings)
    evidence: dict[str, dict[int, list[dict[str, Any]]]] = {}
    sources: dict[str, Any] = {}
    for aspect, query in aspects.items():
        evidence[aspect] = {}
        for i, d in enumerate(docs, start=1):
            res = await retrieve(
                db=db, store=store, embedder=embedder, reranker=reranker, settings=settings,
                scope=Scope(workspace_id, [d["_id"]]), queries=[f"{aspect} {query}"], mode="hybrid", min_vector_score=0.0,
            )  # fmt: skip
            passages = []
            for j, c in enumerate(res.chunks[:PASSAGES_PER_DOC], start=1):
                label = f"D{i}A{list(aspects).index(aspect) + 1}S{j}"
                passages.append({"label": label, "page": c.page_number, "text": c.content})
                sources[label] = {
                    "label": label, "document_index": i, "document_id": str(d["_id"]), "document_title": d["title"],
                    "page_number": c.page_number, "page_is_exact": c.metadata.get("page_basis") == "physical",
                    "snippet": c.content[:500], "chunk_id": c.chunk_id,
                }  # fmt: skip
            evidence[aspect][i] = passages
    return evidence, sources


def verify_comparison(
    r: ComparisonResult, sources: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Keep only points whose labels exist; a similarity/difference/conflict with no valid source is dropped."""
    stats = {"dropped_points": 0, "removed_labels": 0}
    used: dict[str, Any] = {}

    def clean(points: list, need_source: bool) -> list[dict[str, Any]]:
        out = []
        for p in points:
            valid = [s for s in dict.fromkeys(p.sources) if s in sources]
            stats["removed_labels"] += len(p.sources) - len(valid)
            if need_source and not valid:
                stats["dropped_points"] += 1
                continue
            used.update({s: sources[s] for s in valid})
            out.append({"text": p.text, "sources": valid})
        return out

    aspects = [
        {
            "aspect": a.aspect,
            "similarities": clean(a.similarities, True), "differences": clean(a.differences, True),
            "conflicts": clean(a.conflicts, True), "missing_information": clean(a.missing_information, False),
        }
        for a in r.aspects
    ]  # fmt: skip
    return {"summary": r.summary, "aspects": aspects, "sources": used}, stats


async def run_comparison_job(
    db: AsyncDatabase, settings: Settings, store: Any, job_id: ObjectId
) -> None:
    job = await db.processing_jobs.find_one({"_id": job_id})
    if not job or job["state"] in {"completed", "failed"}:
        return
    rec = await db.document_comparisons.find_one({"_id": job["comparison_id"]})
    if not rec:
        return await set_job(db, job_id, "failed", error="gone")
    ws = await db.workspaces.find_one({"_id": rec["workspace_id"]})
    attempts = job["attempts"] + 1
    await set_job(db, job_id, "running", attempts=attempts)
    await db.document_comparisons.update_one(
        {"_id": rec["_id"]}, {"$set": {"status": "running", "error": None}}
    )
    reason = ai_unavailable_reason(settings, ws)
    try:
        if rec["kind"] == "versions":
            result = await _compare_versions(db, settings, store, rec, reason)
            ver: dict[str, Any] = {}
        else:
            if reason:
                await db.document_comparisons.update_one(
                    {"_id": rec["_id"]},
                    {"$set": {"status": "unavailable", "error": reason, "updated_at": utcnow()}},
                )
                return await set_job(db, job_id, "completed")
            result, ver = await _compare_documents(db, settings, rec)
    except LLMError as e:
        if e.retryable and attempts < settings.job_max_attempts:
            await set_job(db, job_id, "retrying")
            raise RetryableError(e.message) from e
        await db.document_comparisons.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "failed", "error": e.message, "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "failed", error=e.message)
    except PermanentError as e:
        await db.document_comparisons.update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "failed", "error": str(e), "updated_at": utcnow()}},
        )
        return await set_job(db, job_id, "failed", error=str(e))
    await db.document_comparisons.update_one(
        {"_id": rec["_id"]},
        {"$set": {"status": "completed", "result": result, "verification": ver, "prompt_version": cp.PROMPT_VERSION, "updated_at": utcnow()}},
    )  # fmt: skip
    await set_job(db, job_id, "completed", progress=1.0)


async def _compare_documents(
    db: AsyncDatabase, settings: Settings, rec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    found = {
        d["_id"]: d
        async for d in db.documents.find(
            {
                "_id": {"$in": rec["document_ids"]},
                "workspace_id": rec["workspace_id"],
                "deleted_at": None,
            }
        )
    }
    if len(found) != len(rec["document_ids"]):
        raise PermanentError("One of the documents no longer exists")
    docs = [found[i] for i in rec["document_ids"]]
    aspects = {a: DEFAULT_ASPECTS.get(a, a) for a in rec.get("aspects") or DEFAULT_ASPECTS}
    evidence, sources = await gather_evidence(db, settings, rec["workspace_id"], docs, aspects)
    if not sources:
        raise PermanentError("No indexed content was found in these documents")
    meta = [{"index": i, "title": d["title"]} for i, d in enumerate(docs, start=1)]
    llm = registry.get_llm(settings)
    parsed, usage = await llm.structured(
        cp.SYSTEM, [{"role": "user", "content": cp.render_evidence(meta, evidence)}], ComparisonResult, max_tokens=8000
    )  # fmt: skip
    await record_usage(
        db, workspace_id=rec["workspace_id"], user_id=rec.get("created_by"), kind="comparison", provider=llm.name,
        model=llm.model, tokens_in=usage.input_tokens, tokens_out=usage.output_tokens, latency_ms=usage.latency_ms,
    )  # fmt: skip
    result, stats = verify_comparison(parsed, sources)
    result["documents"] = [
        {"index": m["index"], "document_id": str(d["_id"]), "title": d["title"]}
        for m, d in zip(meta, docs, strict=True)
    ]
    # Side-by-side view is deterministic: the top retrieved passages per document for each aspect.
    result["side_by_side"] = [
        {"aspect": a, "columns": [{"document_index": i, "passages": [{"label": p["label"], "page": p["page"], "text": p["text"][:600]} for p in ps]} for i, ps in per.items()]}
        for a, per in evidence.items()
    ]  # fmt: skip
    return result, stats


async def _compare_versions(
    db: AsyncDatabase, settings: Settings, store: Any, rec: dict[str, Any], reason: str | None
) -> dict[str, Any]:
    va = await db.document_versions.find_one({"_id": rec["version_ids"][0]})
    vb = await db.document_versions.find_one({"_id": rec["version_ids"][1]})
    if not va or not vb:
        raise PermanentError("A version no longer exists")
    diff = diff_versions(await load_extracted_doc(store, va), await load_extracted_doc(store, vb))
    diff["versions"] = [
        {"version_no": va["version_no"], "filename": va["filename"]},
        {"version_no": vb["version_no"], "filename": vb["filename"]},
    ]
    diff["summary"], diff["notable_changes"], diff["summary_note"] = None, [], None
    if reason:
        diff["summary_note"] = f"No AI summary: {reason}"
    elif any(diff["stats"][k] for k in ("added", "removed", "changed")):
        llm = registry.get_llm(settings)
        listing = "\n".join(
            [f"ADDED (p.{x['page']}): {x['text'][:400]}" for x in diff["added"][:25]]
            + [f"REMOVED (p.{x['page']}): {x['text'][:400]}" for x in diff["removed"][:25]]
            + [
                f"CHANGED (p.{x['new_page']}): '{x['before'][:300]}' -> '{x['after'][:300]}'"
                for x in diff["changed"][:25]
            ]
        )
        s, usage = await llm.structured(
            cp.VERSION_SYSTEM,
            [
                {
                    "role": "user",
                    "content": cp.render_evidence(
                        [], {"changes": {1: [{"label": "C", "page": None, "text": listing}]}}
                    ),
                }
            ],
            VersionSummary,
            max_tokens=2000,
        )
        await record_usage(
            db,
            workspace_id=rec["workspace_id"],
            user_id=rec.get("created_by"),
            kind="comparison",
            provider=llm.name,
            model=llm.model,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
        )
        diff["summary"], diff["notable_changes"] = s.summary, s.notable_changes
    return diff


async def create_comparison(
    db: AsyncDatabase, *, workspace_id: ObjectId, user_id: ObjectId, kind: str, title: str,
    document_ids: list[ObjectId], version_ids: list[ObjectId], aspects: list[str] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:  # fmt: skip
    now = utcnow()
    rec = {
        "workspace_id": workspace_id, "kind": kind, "title": title, "status": "pending", "error": None,
        "document_ids": document_ids, "version_ids": version_ids, "aspects": aspects, "result": None,
        "verification": None, "created_by": user_id, "created_at": now, "updated_at": now,
    }  # fmt: skip
    rec["_id"] = (await db.document_comparisons.insert_one(rec)).inserted_id
    job = {
        "workspace_id": workspace_id, "type": "comparison", "comparison_id": rec["_id"], "state": "queued",
        "attempts": 0, "stages": {}, "progress": 0.0, "error": None, "created_at": now, "updated_at": now,
    }  # fmt: skip
    job["_id"] = (await db.processing_jobs.insert_one(job)).inserted_id
    return rec, job
