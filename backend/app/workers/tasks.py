import asyncio
from datetime import timedelta

from bson import ObjectId

from app.core.config import get_settings
from app.core.db import create_client
from app.modules.ingestion.orchestrator import RetryLater, run_job
from app.modules.ingestion.queue import CeleryQueue, recover_stuck_jobs
from app.modules.ingestion.stages import register_default_stages
from app.storage.factory import build_object_store
from app.workers.celery_app import celery_app


async def _process(job_id: str) -> None:
    settings = get_settings()
    client = create_client(settings)  # per-task client: each task has its own event loop
    try:
        register_default_stages()
        await run_job(
            client[settings.mongodb_db], settings, build_object_store(settings), ObjectId(job_id)
        )
    finally:
        await client.close()


@celery_app.task(bind=True, name="documind.process_document", max_retries=None)
def process_document(self, job_id: str) -> None:  # noqa: ANN001
    try:
        asyncio.run(_process(job_id))
    except RetryLater as r:
        raise self.retry(countdown=r.countdown, exc=r) from r


async def _recover() -> int:
    settings = get_settings()
    client = create_client(settings)
    try:
        return await recover_stuck_jobs(
            client[settings.mongodb_db], CeleryQueue(), timedelta(minutes=15)
        )
    finally:
        await client.close()


@celery_app.task(name="documind.recover_stuck_jobs")
def recover_stuck() -> int:
    return asyncio.run(_recover())
