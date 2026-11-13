from celery import Celery

from app.core.config import get_settings

_s = get_settings()

celery_app = Celery(
    "documind", broker=_s.redis_url, backend=_s.redis_url, include=["app.workers.tasks"]
)
celery_app.conf.update(
    task_acks_late=True,  # a crashed worker's task is redelivered
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # long tasks: don't hoard
    task_time_limit=60 * 60,
    task_soft_time_limit=55 * 60,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "recover-stuck-jobs": {"task": "documind.recover_stuck_jobs", "schedule": 300.0},
    },
)
