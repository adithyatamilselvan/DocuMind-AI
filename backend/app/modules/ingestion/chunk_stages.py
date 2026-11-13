"""Pipeline stages after extraction: chunk -> embed -> index."""

import time
from typing import Any

from pymongo import UpdateOne

from app.ai.providers.embeddings import build_embedder
from app.core.ids import utcnow
from app.modules.chunking.service import chunk_document
from app.modules.ingestion.errors import PermanentError, RetryableError
from app.modules.ingestion.orchestrator import StageContext
from app.modules.usage.service import record_usage
from app.modules.vector_search.factory import build_vector_store


def embedding_text(title: str, section_path: list[str], content: str) -> str:
    """What is actually embedded: the chunk plus its document title and section path, so a
    chunk that says 'it grew 12%' still carries the context of what it belongs to."""
    head = " > ".join(section_path)
    prefix = f"{title}\n{head}\n" if head else f"{title}\n"
    return (prefix + content)[:8000]


async def chunk_stage(ctx: StageContext) -> None:
    from app.modules.ingestion.stages import load_extracted  # avoid import cycle

    doc = await load_extracted(ctx)
    drafts = chunk_document(doc)
    if not drafts:
        raise PermanentError("No searchable content could be produced from this document")
    version_id = ctx.version["_id"]
    await ctx.db.document_chunks.delete_many({"document_version_id": version_id})  # idempotent
    now = utcnow()
    rows: list[dict[str, Any]] = [
        {
            "workspace_id": ctx.workspace_id,
            "document_id": ctx.document["_id"],
            "document_version_id": version_id,
            "chunk_id": f"{version_id}:{d.chunk_index}",
            "chunk_index": d.chunk_index,
            "content": d.content,
            "embedding": None,
            "page_number": d.page_number,
            "section_heading": d.section_heading,
            "section_path": d.section_path,
            "token_count": d.token_count,
            "content_hash": d.content_hash,
            "embedding_model": None,
            "embedding_version": None,
            "is_current": False,  # flipped atomically by the index stage
            "metadata": {**d.metadata, "type": d.type},
            "created_at": now,
        }
        for d in drafts
    ]
    for i in range(0, len(rows), 500):
        await ctx.db.document_chunks.insert_many(rows[i : i + 500])
    await ctx.db.document_versions.update_one(
        {"_id": version_id}, {"$set": {"chunk_count": len(rows)}}
    )


async def embed_stage(ctx: StageContext) -> None:
    settings = ctx.settings
    embedder = build_embedder(settings)
    if settings.embeds_externally:
        ws = await ctx.db.workspaces.find_one({"_id": ctx.workspace_id})
        if not (ws and ws.get("settings", {}).get("ai_processing_consent")):
            raise PermanentError("External AI processing is not enabled for this workspace")
    version_id = ctx.version["_id"]
    total = await ctx.db.document_chunks.count_documents({"document_version_id": version_id})
    batch = embedder.max_batch
    done = total - await ctx.db.document_chunks.count_documents(
        {"document_version_id": version_id, "embedding": None}
    )
    while True:
        # Re-query each round so a resumed job only embeds what is still missing.
        pending = [
            c
            async for c in ctx.db.document_chunks.find(
                {"document_version_id": version_id, "embedding": None},
                {"content": 1, "section_path": 1},
            )
            .sort("chunk_index", 1)
            .limit(batch)
        ]
        if not pending:
            break
        texts = [
            embedding_text(ctx.document["title"], c.get("section_path", []), c["content"])
            for c in pending
        ]
        started = time.monotonic()
        vectors = await embedder.embed_documents(texts)
        if len(vectors) != len(pending):
            raise RetryableError("Embedding provider returned a different number of vectors")
        await ctx.db.document_chunks.bulk_write(
            [
                UpdateOne(
                    {"_id": c["_id"]},
                    {
                        "$set": {
                            "embedding": v,
                            "embedding_model": embedder.model,
                            "embedding_version": embedder.version,
                        }
                    },
                )
                for c, v in zip(pending, vectors, strict=True)
            ]
        )
        await record_usage(
            ctx.db, workspace_id=ctx.workspace_id, user_id=ctx.document.get("owner_id"), kind="embedding",
            provider=embedder.name, model=embedder.model,
            tokens_in=sum(max(1, len(t) // 4) for t in texts),
            latency_ms=int((time.monotonic() - started) * 1000), meta={"document_id": str(ctx.document["_id"])},
        )  # fmt: skip
        done += len(pending)
        await ctx.progress(done / max(total, 1))


async def index_stage(ctx: StageContext) -> None:
    """Make the new version searchable. Verifies, never assumes, that the search index exists."""
    version_id = ctx.version["_id"]
    total = await ctx.db.document_chunks.count_documents({"document_version_id": version_id})
    missing = await ctx.db.document_chunks.count_documents(
        {"document_version_id": version_id, "embedding": None}
    )
    if total == 0 or missing:
        raise RetryableError(f"{missing} of {total} chunks are not embedded yet")

    store = build_vector_store(ctx.settings)
    health = await store.health(ctx.db)
    if not health["ready"]:
        raise RetryableError(f"Search index is not ready: {health}")

    # Atomic-ish switch: new chunks become visible, then older versions' chunks are removed.
    await ctx.db.document_chunks.update_many(
        {"document_version_id": version_id}, {"$set": {"is_current": True}}
    )
    await ctx.db.document_chunks.delete_many(
        {"document_id": ctx.document["_id"], "document_version_id": {"$ne": version_id}}
    )
