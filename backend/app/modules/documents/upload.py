import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from fastapi import UploadFile
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError, conflict
from app.core.ids import utcnow
from app.modules.documents import service
from app.modules.documents.malware import build_scanner
from app.modules.documents.schemas import DocumentOut
from app.modules.documents.states import DocumentStatus
from app.modules.documents.validation import detect_type, sanitize_filename
from app.modules.ingestion.orchestrator import create_job
from app.modules.ingestion.queue import JobQueue
from app.storage.base import ObjectStore

CHUNK = 1024 * 1024


@dataclass
class Received:
    path: str
    size: int
    sha256: str


async def spool_upload(file: UploadFile, max_bytes: int) -> Received:
    """Stream the upload to a temp file computing SHA-256 and enforcing the size limit."""
    fd, path = tempfile.mkstemp(prefix="documind-upload-")
    h = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        413, "too_large", f"File exceeds the {max_bytes // 1024 // 1024} MB limit"
                    )
                h.update(chunk)
                await asyncio.to_thread(out.write, chunk)
    except BaseException:
        os.unlink(path)
        raise
    if size == 0:
        os.unlink(path)
        raise AppError(400, "empty_file", "The file is empty")
    return Received(path=path, size=size, sha256=h.hexdigest())


def storage_key(workspace_id: ObjectId, document_id: ObjectId, version_id: ObjectId) -> str:
    return f"workspaces/{workspace_id}/documents/{document_id}/{version_id}/original"


@dataclass
class UploadResult:
    filename: str
    outcome: str  # created | duplicate | rejected
    document: DocumentOut | None = None
    existing_document_id: str | None = None
    error_code: str | None = None
    error: str | None = None


async def _find_duplicate(
    db: AsyncDatabase, workspace_id: ObjectId, sha256: str
) -> dict[str, Any] | None:
    return await db.documents.find_one(
        {"workspace_id": workspace_id, "sha256": sha256, "deleted_at": None}
    )


async def ingest_new_document(
    db: AsyncDatabase, store: ObjectStore, queue: JobQueue, settings: Settings,
    *, workspace_id: ObjectId, user_id: ObjectId, file: UploadFile,
) -> UploadResult:  # fmt: skip
    filename = sanitize_filename(file.filename)
    received: Received | None = None
    try:
        received = await spool_upload(file, settings.max_upload_bytes)
        detected = detect_type(received.path, filename)
        await build_scanner(settings).scan_file(received.path)
        if dup := await _find_duplicate(db, workspace_id, received.sha256):
            return UploadResult(
                filename, "duplicate", existing_document_id=str(dup["_id"]),
                error_code="duplicate", error=f'Identical to existing document "{dup["title"]}"',
            )  # fmt: skip
        title = filename.rsplit(".", 1)[0] if "." in filename else filename
        doc, version = await service.create_document(
            db, workspace_id=workspace_id, owner_id=user_id, filename=filename,
            title=title or filename, mime_type=detected.mime, size_bytes=received.size,
            sha256=received.sha256, storage_key="pending",
        )  # fmt: skip
        key = storage_key(workspace_id, doc["_id"], version["_id"])
        try:
            await store.put_file(key, received.path, detected.mime)
        except Exception:
            await db.document_versions.delete_one({"_id": version["_id"]})
            await db.documents.delete_one({"_id": doc["_id"]})
            raise
        await db.document_versions.update_one(
            {"_id": version["_id"]}, {"$set": {"storage_key": key}}
        )
        await _queue_processing(db, queue, doc["_id"], workspace_id, version["_id"])
        fresh = await db.documents.find_one({"_id": doc["_id"]})
        return UploadResult(filename, "created", document=DocumentOut.from_doc(fresh))
    except AppError as e:
        return UploadResult(filename, "rejected", error_code=e.code, error=e.message)
    finally:
        if received:
            os.unlink(received.path)
        await file.close()


async def _queue_processing(
    db: AsyncDatabase,
    queue: JobQueue,
    document_id: ObjectId,
    workspace_id: ObjectId,
    version_id: ObjectId,
) -> None:
    if not await service.set_status(db, document_id, DocumentStatus.QUEUED):
        raise conflict("Document cannot be queued from its current status", "bad_state")
    job = await create_job(db, workspace_id, document_id, version_id)
    try:
        await queue.enqueue(job["_id"])
    except Exception:
        await service.set_status(
            db, document_id, DocumentStatus.FAILED, error="Could not queue processing"
        )
        raise


async def add_version(
    db: AsyncDatabase, store: ObjectStore, queue: JobQueue, settings: Settings,
    *, workspace_id: ObjectId, user_id: ObjectId, document: dict[str, Any], file: UploadFile,
) -> UploadResult:  # fmt: skip
    await service.ensure_not_in_progress(document)
    filename = sanitize_filename(file.filename)
    received: Received | None = None
    try:
        received = await spool_upload(file, settings.max_upload_bytes)
        detected = detect_type(received.path, filename)
        await build_scanner(settings).scan_file(received.path)
        if received.sha256 == document["sha256"]:
            return UploadResult(
                filename, "duplicate", existing_document_id=str(document["_id"]),
                error_code="same_as_current", error="Identical to the current version",
            )  # fmt: skip
        version_no = document["version_count"] + 1
        now = utcnow()
        version: dict[str, Any] = {
            "document_id": document["_id"], "workspace_id": workspace_id, "version_no": version_no,
            "storage_key": "pending", "sha256": received.sha256, "size_bytes": received.size,
            "mime_type": detected.mime, "filename": filename, "created_by": user_id, "created_at": now,
        }  # fmt: skip
        version["_id"] = (await db.document_versions.insert_one(version)).inserted_id
        key = storage_key(workspace_id, document["_id"], version["_id"])
        try:
            await store.put_file(key, received.path, detected.mime)
        except Exception:
            await db.document_versions.delete_one({"_id": version["_id"]})
            raise
        await db.document_versions.update_one(
            {"_id": version["_id"]}, {"$set": {"storage_key": key}}
        )
        await db.documents.update_one(
            {"_id": document["_id"]},
            {"$set": {
                "current_version_id": version["_id"], "version_count": version_no,
                "filename": filename, "mime_type": detected.mime, "size_bytes": received.size,
                "sha256": received.sha256, "page_count": None, "updated_at": now,
            }},
        )  # fmt: skip
        await _queue_processing(db, queue, document["_id"], workspace_id, version["_id"])
        fresh = await db.documents.find_one({"_id": document["_id"]})
        return UploadResult(filename, "created", document=DocumentOut.from_doc(fresh))
    except AppError as e:
        return UploadResult(filename, "rejected", error_code=e.code, error=e.message)
    finally:
        if received:
            os.unlink(received.path)
        await file.close()


async def retry_document(
    db: AsyncDatabase, queue: JobQueue, workspace_id: ObjectId, document: dict[str, Any]
) -> None:
    if document["status"] != DocumentStatus.FAILED.value:
        raise conflict("Only failed documents can be retried", "bad_state")
    await db.document_chunks.delete_many({"document_version_id": document["current_version_id"]})
    await _queue_processing(
        db, queue, document["_id"], workspace_id, document["current_version_id"]
    )
