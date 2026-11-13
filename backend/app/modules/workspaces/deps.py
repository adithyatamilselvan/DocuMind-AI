from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from fastapi import Depends

from app.core.errors import forbidden, not_found
from app.core.ids import to_oid
from app.modules.auth.deps import DB, AuthUser
from app.modules.workspaces.roles import Role


@dataclass
class WorkspaceContext:
    """Resolved tenant scope. Every tenant-owned query MUST filter by `workspace_id`."""

    workspace: dict[str, Any]
    user: dict[str, Any]
    role: Role

    @property
    def workspace_id(self) -> ObjectId:
        return self.workspace["_id"]

    @property
    def user_id(self) -> ObjectId:
        return self.user["_id"]


async def _resolve(workspace_id: str, auth: AuthUser, db: DB) -> WorkspaceContext:
    wid = to_oid(workspace_id, "Workspace")
    # Non-members get 404 (not 403) so workspace existence is not revealed.
    membership = await db.memberships.find_one(
        {"workspace_id": wid, "user_id": auth.id, "status": "active"}
    )
    workspace = await db.workspaces.find_one({"_id": wid, "deleted_at": None})
    if not membership or not workspace:
        raise not_found("Workspace not found")
    return WorkspaceContext(workspace=workspace, user=auth.user, role=Role(membership["role"]))


def require_role(minimum: Role) -> Callable[..., Awaitable[WorkspaceContext]]:
    async def dep(ctx: WorkspaceContext = Depends(_resolve)) -> WorkspaceContext:
        if not ctx.role.at_least(minimum):
            raise forbidden(f"Requires {minimum.value} role")
        return ctx

    return dep


viewer_ctx = require_role(Role.viewer)
editor_ctx = require_role(Role.editor)
admin_ctx = require_role(Role.admin)
owner_ctx = require_role(Role.owner)
