from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.ids import to_oid
from app.core.pagination import Page, PageParams
from app.modules.audit import service as audit
from app.modules.auth.deps import DB
from app.modules.documents import service
from app.modules.documents.schemas import (
    BulkIn,
    BulkOut,
    DocumentOut,
    DocumentQuery,
    UpdateDocumentIn,
)
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]


@router.get("", response_model=Page[DocumentOut])
async def list_documents(
    ctx: Viewer, db: DB,
    query: Annotated[DocumentQuery, Depends()],
    paging: Annotated[PageParams, Depends()],
):  # fmt: skip
    items, total = await service.list_documents(
        db, ctx.workspace_id, query, paging.skip, paging.page_size
    )
    return Page[DocumentOut](
        items=[DocumentOut.from_doc(d) for d in items],
        total=total, page=paging.page, page_size=paging.page_size,
    )  # fmt: skip


@router.post("/bulk", response_model=BulkOut)
async def bulk_action(body: BulkIn, ctx: Editor, db: DB):
    affected = await service.bulk(db, ctx.workspace_id, body)
    await audit.record(
        db, action=f"document.bulk.{body.action}", actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id, target={"count": affected},
    )  # fmt: skip
    return BulkOut(affected=affected)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, ctx: Viewer, db: DB):
    return DocumentOut.from_doc(
        await service.get_document(db, ctx.workspace_id, document_id, touch=True)
    )


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(document_id: str, body: UpdateDocumentIn, ctx: Editor, db: DB):
    doc = await service.update_document(db, ctx.workspace_id, document_id, body)
    return DocumentOut.from_doc(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, ctx: Editor, db: DB) -> Response:
    doc = await service.get_document(db, ctx.workspace_id, document_id)
    await service.delete_documents(db, ctx.workspace_id, [to_oid(document_id)])
    await audit.record(
        db, action="document.delete", actor_id=ctx.user_id, workspace_id=ctx.workspace_id,
        target={"document_id": document_id, "title": doc["title"]},
    )  # fmt: skip
    return Response(status_code=status.HTTP_204_NO_CONTENT)
