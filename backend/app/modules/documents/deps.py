from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.modules.ingestion.queue import JobQueue
from app.storage.base import ObjectStore


def get_store(request: Request) -> ObjectStore:
    return request.app.state.store


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


Store = Annotated[ObjectStore, Depends(get_store)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Config = Annotated[Settings, Depends(get_settings)]
