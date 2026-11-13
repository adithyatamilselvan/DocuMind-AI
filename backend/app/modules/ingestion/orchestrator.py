"""Ingestion orchestrator: runs the registered stages for one processing job.

Guarantees:
- Idempotent/resumable: completed stages are recorded on the job and skipped on re-run.
- Document status only moves through validated transitions.
- COMPLETED is set only after every stage succeeded.
- Transient failures raise RetryLater (queue re-runs with backoff); permanent ones mark FAILED.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.documents import service as documents
from app.modules.documents.states import DocumentStatus
from app.modules.ingestion.errors import (
    DocumentGone,
    PermanentError,
    RetryableError,
    RetryLater,
)
from app.storage.base import ObjectStore

log = logging.getLogger("documind.ingestion")


@dataclass
class StageContext:
    db: AsyncDatabase
    settings: Settings
    store: ObjectStore
    document: dict[str, Any]
    version: dict[str, Any]
    job: dict[str, Any]
    data: dict[str, Any] = field(default_factory=dict)  # scratch values shared between stages

    @property
    def workspace_id(self) -> ObjectId:
        return self.document["workspace_id"]

    async def enter(self, status: DocumentStatus) -> None:
        """Move the document into `status` (e.g. OCR_PROCESSING) via a validated transition."""
        current = DocumentStatus(
            (await self.db.documents.find_one({"_id": self.document["_id"]}))["status"]
        )
        if current == status:
            return
        if not await documents.set_status(self.db, self.document["_id"], status):
            raise PermanentError(f"Illegal status transition {current} -> {status}")

    async def progress(self, fraction: float) -> None:
        await self.db.processing_jobs.update_one(
            {"_id": self.job["_id"]}, {"$set": {"stage_progress": fraction, "updated_at": utcnow()}}
        )


StageFn = Callable[[StageContext], Awaitable[None]]


@dataclass(frozen=True)
class Stage:
    name: str
    status: DocumentStatus
    run: StageFn


# Populated by app.modules.ingestion.stages.register_default_stages().
STAGES: list[Stage] = []


async def create_job(
    db: AsyncDatabase, workspace_id: ObjectId, document_id: ObjectId, version_id: ObjectId
) -> dict[str, Any]:
    now = utcnow()
    job = {
        "workspace_id": workspace_id, "document_id": document_id,
        "document_version_id": version_id, "type": "ingest", "state": "queued",
        "attempts": 0, "stages": {}, "progress": 0.0, "stage_progress": 0.0, "error": None,
        "created_at": now, "updated_at": now,
    }  # fmt: skip
    job["_id"] = (await db.processing_jobs.insert_one(job)).inserted_id
    return job


async def _fail(
    db: AsyncDatabase, job: dict[str, Any], document_id: ObjectId, message: str
) -> None:
    await documents.set_status(db, document_id, DocumentStatus.FAILED, error=message)
    await db.processing_jobs.update_one(
        {"_id": job["_id"]}, {"$set": {"state": "failed", "error": message, "updated_at": utcnow()}}
    )


async def _purge_version_chunks(db: AsyncDatabase, version_id: ObjectId) -> None:
    await db.document_chunks.delete_many({"document_version_id": version_id})


async def run_job(
    db: AsyncDatabase,
    settings: Settings,
    store: ObjectStore,
    job_id: ObjectId,
    stages: list[Stage] | None = None,
) -> None:
    stages = STAGES if stages is None else stages
    job = await db.processing_jobs.find_one({"_id": job_id})
    if not job or job["state"] in {"completed", "failed"}:
        return
    document = await db.documents.find_one({"_id": job["document_id"], "deleted_at": None})
    version = await db.document_versions.find_one({"_id": job["document_version_id"]})
    if not document or not version:
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "failed", "error": "Document no longer exists"}}
        )
        return
    if not stages:
        await _fail(db, job, document["_id"], "No processing stages are configured")
        return

    attempts = job["attempts"] + 1
    await db.processing_jobs.update_one(
        {"_id": job_id},
        {"$set": {"state": "running", "attempts": attempts, "updated_at": utcnow()}},
    )
    ctx = StageContext(db, settings, store, document, version, job)

    try:
        status = DocumentStatus(document["status"])
        if status == DocumentStatus.QUEUED:
            await ctx.enter(DocumentStatus.PROCESSING)
        elif status in {DocumentStatus.COMPLETED, DocumentStatus.FAILED, DocumentStatus.UPLOADING}:
            return
        # else: resuming after a crash; status is already an in-progress one.

        for index, stage in enumerate(stages):
            if job["stages"].get(stage.name, {}).get("state") == "done":
                continue
            if not await db.documents.find_one({"_id": document["_id"], "deleted_at": None}):
                raise DocumentGone
            await _enter_for_resume(ctx, stage.status)
            await stage.run(ctx)
            job["stages"][stage.name] = {"state": "done", "finished_at": utcnow()}
            await db.processing_jobs.update_one(
                {"_id": job_id},
                {"$set": {
                    f"stages.{stage.name}": job["stages"][stage.name],
                    "progress": (index + 1) / len(stages), "updated_at": utcnow(),
                }},
            )  # fmt: skip

        if not await documents.set_status(db, document["_id"], DocumentStatus.COMPLETED):
            raise PermanentError("Document could not be marked completed")
        await db.processing_jobs.update_one(
            {"_id": job_id},
            {"$set": {"state": "completed", "progress": 1.0, "updated_at": utcnow()}},
        )
    except DocumentGone:
        await _purge_version_chunks(db, version["_id"])
        await db.processing_jobs.update_one(
            {"_id": job_id}, {"$set": {"state": "failed", "error": "deleted"}}
        )
    except PermanentError as e:
        await _fail(db, job, document["_id"], str(e))
    except Exception as e:
        log.exception("Job %s attempt %s failed", job_id, attempts)
        if attempts < settings.job_max_attempts:
            await db.processing_jobs.update_one(
                {"_id": job_id}, {"$set": {"state": "retrying", "updated_at": utcnow()}}
            )
            raise RetryLater(countdown=min(300, 5 * 2 ** (attempts - 1))) from e
        await _fail(db, job, document["_id"], "Processing failed after several attempts")


_ORDER = [
    DocumentStatus.PROCESSING, DocumentStatus.EXTRACTING, DocumentStatus.OCR_PROCESSING,
    DocumentStatus.CHUNKING, DocumentStatus.EMBEDDING, DocumentStatus.INDEXING,
]  # fmt: skip


async def _enter_for_resume(ctx: StageContext, status: DocumentStatus) -> None:
    """Enter a stage's status. When resuming after a crash the document may already be in a
    LATER status than the first unfinished stage; in that case reset it via the recovery path."""
    current = DocumentStatus(
        (await ctx.db.documents.find_one({"_id": ctx.document["_id"]}))["status"]
    )
    if current == status:
        return
    if await documents.set_status(ctx.db, ctx.document["_id"], status):
        return
    if current in _ORDER and status in _ORDER:  # resume: explicit, audited rewind
        await ctx.db.documents.update_one(
            {"_id": ctx.document["_id"]}, {"$set": {"status": status.value, "updated_at": utcnow()}}
        )
        return
    raise PermanentError(f"Illegal status transition {current} -> {status}")


__all__ = ["DocumentGone", "PermanentError", "RetryLater", "RetryableError"]
