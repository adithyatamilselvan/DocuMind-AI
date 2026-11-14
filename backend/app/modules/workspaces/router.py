from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.ids import to_oid
from app.modules.audit import service as audit
from app.modules.auth.deps import DB, AuthUser
from app.modules.workspaces import service
from app.modules.workspaces.deps import WorkspaceContext, admin_ctx, owner_ctx, viewer_ctx
from app.modules.workspaces.schemas import (
    AddMemberIn,
    CreateWorkspaceIn,
    MemberOut,
    UpdateMemberIn,
    UpdateWorkspaceIn,
    WorkspaceOut,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
Viewer = Annotated[WorkspaceContext, Depends(viewer_ctx)]
Admin = Annotated[WorkspaceContext, Depends(admin_ctx)]
Owner = Annotated[WorkspaceContext, Depends(owner_ctx)]


@router.get("", response_model=list[WorkspaceOut])
async def list_my_workspaces(auth: AuthUser, db: DB):
    return [
        WorkspaceOut.from_docs(ws, role) for ws, role in await service.list_for_user(db, auth.id)
    ]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(body: CreateWorkspaceIn, auth: AuthUser, db: DB):
    from app.modules.workspaces.roles import Role

    ws = await service.create_workspace(db, auth.id, body.name)
    await audit.record(db, action="workspace.create", actor_id=auth.id, workspace_id=ws["_id"])
    return WorkspaceOut.from_docs(ws, Role.owner)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(ctx: Viewer):
    return WorkspaceOut.from_docs(ctx.workspace, ctx.role)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(body: UpdateWorkspaceIn, ctx: Admin, db: DB):
    ws = await service.update_workspace(
        db, ctx.workspace_id, body.name, body.settings.model_dump() if body.settings else None
    )
    await audit.record(
        db, action="workspace.update", actor_id=ctx.user_id, workspace_id=ctx.workspace_id
    )
    return WorkspaceOut.from_docs(ws, ctx.role)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(request: Request, ctx: Owner, db: DB) -> Response:
    """Permanently deletes the workspace with all its documents, files, analyses and conversations."""
    from app.modules.workspaces.purge import purge_workspace

    await purge_workspace(db, request.app.state.store, ctx.workspace_id)
    await audit.record(
        db, action="workspace.delete", actor_id=ctx.user_id, workspace_id=ctx.workspace_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(ctx: Viewer, db: DB):
    return await service.list_members(db, ctx.workspace_id)


@router.post(
    "/{workspace_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
async def add_member(body: AddMemberIn, ctx: Admin, db: DB):
    member = await service.add_member(db, ctx.workspace_id, ctx.role, body.email, body.role)
    await audit.record(
        db,
        action="member.add",
        actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        target={"user_id": str(member["user_id"]), "role": body.role.value},
    )
    return member


@router.patch("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_member(user_id: str, body: UpdateMemberIn, ctx: Admin, db: DB) -> Response:
    await service.change_member_role(
        db, ctx.workspace_id, ctx.role, to_oid(user_id, "Member"), body.role
    )
    await audit.record(
        db,
        action="member.role",
        actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        target={"user_id": user_id, "role": body.role.value},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: str, ctx: Viewer, db: DB) -> Response:
    # Any member may remove themselves; removing others requires admin (enforced in the service).
    await service.remove_member(
        db, ctx.workspace_id, ctx.role, ctx.user_id, to_oid(user_id, "Member")
    )
    await audit.record(
        db,
        action="member.remove",
        actor_id=ctx.user_id,
        workspace_id=ctx.workspace_id,
        target={"user_id": user_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
