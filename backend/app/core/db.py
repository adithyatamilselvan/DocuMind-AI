from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings


def create_client(settings: Settings) -> AsyncMongoClient:
    return AsyncMongoClient(settings.mongodb_uri, tz_aware=True, serverSelectionTimeoutMS=5000)


def get_db(request: Request) -> AsyncDatabase:
    return request.app.state.db
