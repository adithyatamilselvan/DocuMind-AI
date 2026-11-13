from app.core.config import Settings
from app.storage.base import ObjectStore
from app.storage.local import LocalObjectStore
from app.storage.s3 import S3ObjectStore


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        return S3ObjectStore(settings)
    if settings.env == "production":
        raise RuntimeError("STORAGE_BACKEND=local is not allowed in production")
    return LocalObjectStore(settings.local_storage_dir)
