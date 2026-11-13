"""Upload, versions, download, retry and processing status for documents."""

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.errors import AppError, not_found
from app.core.ids import to_oid
from app.modules.audit import service as audit
from app.modules.auth.deps import DB
from app.modules.documents import service, upload
from app.modules.documents.deps import Config, Queue, Store
from app.modules.documents.schemas import DocumentOut
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx
from app.storage.base import ObjectNotFoundError

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]


class UploadResultOut(BaseModel):
    filename: str
    outcome: str
    document: DocumentOut | None = None
    existing_document_id: str | None = None
    error_code: str | None = None
    error: str | None = None


class UploadOut(BaseModel):
    results: list[UploadResultOut]


class VersionOut(BaseModel):
    id: str
    version_no: int
    filename: str
    size_bytes: int
    sha256: str
    is_current: bool
    created_at: datetime


class ProcessingOut(BaseModel):
    state: str
    progress: float
    attempts: int
    error: str | None
    stages: dict[str, str]


def require_ai_consent(ctx: WorkspaceContext, settings: Config) -> None:
    """Hosted embeddings/LLMs send document text to a third party: require explicit consent."""
    external = settings.ai_external
    if external and not ctx.workspace.get("settings", {}).get("ai_processing_consent"):
        raise AppError(
            403,
            "ai_consent_required",
            "A workspace admin must allow external AI processing in Settings "
            "before documents can be processed.",
        )


def _check_length(request: Request, settings: Config, files: int) -> None:
    length = request.headers.get("content-length")
    limit = settings.max_upload_bytes * files + 1024 * 1024
    if length and length.isdigit() and int(length) > limit:
        raise AppError(413, "too_large", "Upload is too large")


@router.post("/upload", response_model=UploadOut)
async def upload_documents(
    request: Request,
    ctx: Editor,
    db: DB,
    store: Store,
    queue: Queue,
    settings: Config,
    files: Annotated[list[UploadFile], File()],
):
    require_ai_consent(ctx, settings)
    if not files or len(files) > settings.max_files_per_upload:
        raise AppError(
            400, "bad_file_count", f"Upload 1-{settings.max_files_per_upload} files at a time"
        )
    _check_length(request, settings, len(files))
    results = []
    for f in files:
        r = await upload.ingest_new_document(
            db, store, queue, settings, workspace_id=ctx.workspace_id, user_id=ctx.user_id, file=f
        )
        results.append(UploadResultOut(**r.__dict__))
        if r.outcome == "created" and r.document:
            await audit.record(
                db,
                action="document.upload",
                actor_id=ctx.user_id,
                workspace_id=ctx.workspace_id,
                target={"document_id": str(r.document.id), "filename": r.filename},
            )
    return UploadOut(results=results)


@router.post("/{document_id}/versions", response_model=UploadResultOut)
async def upload_version(
    document_id: str,
    request: Request,
    ctx: Editor,
    db: DB,
    store: Store,
    queue: Queue,
    settings: Config,
    file: Annotated[UploadFile, File()],
):
    require_ai_consent(ctx, settings)
    _check_length(request, settings, 1)
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    r = await upload.add_version(
        db, store, queue, settings, workspace_id=ctx.workspace_id, user_id=ctx.user_id,
        document=doc, file=file,
    )  # fmt: skip
    if r.outcome == "created":
        await audit.record(
            db, action="document.version", actor_id=ctx.user_id,
            workspace_id=ctx.workspace_id, target={"document_id": document_id},
        )  # fmt: skip
    return UploadResultOut(**r.__dict__)


@router.get("/{document_id}/versions", response_model=list[VersionOut])
async def list_versions(document_id: str, ctx: Viewer, db: DB):
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    return [
        VersionOut(
            id=str(v["_id"]),
            version_no=v["version_no"],
            filename=v["filename"],
            size_bytes=v["size_bytes"],
            sha256=v["sha256"],
            is_current=v["_id"] == doc["current_version_id"],
            created_at=v["created_at"],
        )  # fmt: skip
        async for v in db.document_versions.find({"document_id": doc["_id"]}).sort("version_no", -1)
    ]


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    ctx: Viewer,
    db: DB,
    store: Store,
    version: str | None = None,
    inline: bool = False,
):
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    vq: dict[str, Any] = {"document_id": doc["_id"]}
    vq["_id"] = to_oid(version, "Version") if version else doc["current_version_id"]
    v = await db.document_versions.find_one(vq)
    if not v:
        raise not_found("Version not found")
    mime = v["mime_type"]
    disposition = "inline" if inline and mime == "application/pdf" else "attachment"
    stream = store.stream(v["storage_key"])
    try:
        first = await anext(stream)
    except (ObjectNotFoundError, StopAsyncIteration):
        raise not_found("File is not available") from None

    async def body():
        yield first
        async for chunk in stream:
            yield chunk

    return StreamingResponse(
        body(),
        media_type=mime,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(v['filename'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Length": str(v["size_bytes"]),
        },
    )


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_document(document_id: str, ctx: Editor, db: DB, queue: Queue, settings: Config):
    require_ai_consent(ctx, settings)
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    await upload.retry_document(db, queue, ctx.workspace_id, doc)
    await audit.record(
        db, action="document.retry", actor_id=ctx.user_id, workspace_id=ctx.workspace_id,
        target={"document_id": document_id},
    )  # fmt: skip
    return {"status": "queued"}


@router.get("/{document_id}/processing", response_model=ProcessingOut | None)
async def processing_status(document_id: str, ctx: Viewer, db: DB):
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    job = await db.processing_jobs.find_one(
        {"document_id": doc["_id"], "workspace_id": ctx.workspace_id}, sort=[("created_at", -1)]
    )
    if not job:
        return None
    return ProcessingOut(
        state=job["state"], progress=job["progress"], attempts=job["attempts"],
        error=job.get("error"), stages={k: v["state"] for k, v in job["stages"].items()},
    )  # fmt: skip
