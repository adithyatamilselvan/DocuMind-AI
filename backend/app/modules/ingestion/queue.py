import asyncio
import logging
from datetime import timedelta
from typing import Protocol

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.ids import utcnow
from app.modules.ingestion.orchestrator import RetryLater, run_job
from app.storage.base import ObjectStore

log = logging.getLogger("documind.queue")


class JobQueue(Protocol):
    async def enqueue(self, job_id: ObjectId) -> None: ...

    async def close(self) -> None: ...


class InlineQueue:
    """Runs jobs as asyncio tasks inside the API process. Development without Redis only:
    work is lost on restart (recover_stuck_jobs re-enqueues it at the next startup)."""

    def __init__(
        self, db: AsyncDatabase, settings: Settings, store: ObjectStore, concurrency: int = 2
    ):
        self._db, self._settings, self._store = db, settings, store
        self._sem = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job_id: ObjectId) -> None:
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job_id: ObjectId) -> None:
        async with self._sem:
            while True:
                try:
                    follow = await run_job(self._db, self._settings, self._store, job_id)
                    if follow:
                        await self.enqueue(follow)
                    return
                except RetryLater as r:
                    await asyncio.sleep(r.countdown)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Inline job %s crashed", job_id)
                    return

    async def drain(self) -> None:
        """Wait for all in-flight jobs (used by tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)


class CeleryQueue:
    async def enqueue(self, job_id: ObjectId) -> None:
        from app.workers.celery_app import celery_app

        await asyncio.to_thread(
            celery_app.send_task, "documind.process_document", args=[str(job_id)]
        )

    async def close(self) -> None:
        return None


def build_queue(db: AsyncDatabase, settings: Settings, store: ObjectStore) -> JobQueue:
    if settings.job_backend == "celery":
        return CeleryQueue()
    return InlineQueue(db, settings, store)


async def recover_stuck_jobs(db: AsyncDatabase, queue: JobQueue, older_than: timedelta) -> int:
    """Re-enqueue jobs that were left queued/running/retrying by a crashed process."""
    cutoff = utcnow() - older_than
    n = 0
    async for job in db.processing_jobs.find(
        {"state": {"$in": ["queued", "running", "retrying"]}, "updated_at": {"$lt": cutoff}}
    ):
        await queue.enqueue(job["_id"])
        n += 1
    return n
