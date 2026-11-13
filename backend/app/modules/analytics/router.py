from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.analytics import service
from app.modules.analytics.service import Overview
from app.modules.auth.deps import DB
from app.modules.workspaces.deps import WorkspaceContext, viewer_ctx

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])


@router.get("/overview", response_model=Overview)
async def overview(ctx: Annotated[WorkspaceContext, Depends(viewer_ctx)], db: DB):
    return await service.overview(db, ctx.workspace_id)
