from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.modules.auth.deps import DB
from app.modules.collections import service
from app.modules.collections.service import (
    CollectionOut,
    CreateCollectionIn,
    UpdateCollectionIn,
)
from app.modules.workspaces.deps import WorkspaceContext, editor_ctx, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/collections", tags=["collections"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Editor = Annotated[WorkspaceContext, Depends(editor_ctx)]


@router.get("", response_model=list[CollectionOut])
async def list_collections(ctx: Viewer, db: DB):
    return await service.list_collections(db, ctx.workspace_id)


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create_collection(body: CreateCollectionIn, ctx: Editor, db: DB):
    c = await service.create_collection(db, ctx.workspace_id, body)
    return CollectionOut(
        id=c["_id"], name=c["name"], parent_id=c["parent_id"], created_at=c["created_at"]
    )


@router.patch("/{collection_id}", response_model=CollectionOut)
async def rename_collection(collection_id: str, body: UpdateCollectionIn, ctx: Editor, db: DB):
    c = await service.rename_collection(db, ctx.workspace_id, collection_id, body.name)
    return CollectionOut(
        id=c["_id"], name=c["name"], parent_id=c.get("parent_id"), created_at=c["created_at"]
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: str, ctx: Editor, db: DB) -> Response:
    await service.delete_collection(db, ctx.workspace_id, collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
