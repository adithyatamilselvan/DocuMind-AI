from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.errors import AppError, conflict
from app.core.security import verify_password
from app.modules.audit import service as audit
from app.modules.auth.deps import DB, AuthUser
from app.modules.workspaces.deps import Role
from app.modules.workspaces.purge import purge_workspace

router = APIRouter(prefix="/users/me", tags=["privacy"])


def _clean(doc: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in drop and k != "embedding"}


@router.get("/export")
async def export_my_data(auth: AuthUser, db: DB):
    """GDPR-style export of everything tied to the signed-in user (no other users' data, no secrets)."""
    u = auth.user
    memberships = [m async for m in db.memberships.find({"user_id": auth.id})]
    ws_ids = [m["workspace_id"] for m in memberships]
    data = {
        "user": _clean(u, ("password_hash",)),
        "workspaces": [_clean(w) async for w in db.workspaces.find({"_id": {"$in": ws_ids}, "deleted_at": None})],
        "memberships": [_clean(m) for m in memberships],
        "documents": [
            _clean(d) async for d in db.documents.find({"owner_id": auth.id, "deleted_at": None})
        ],
        "conversations": [_clean(c) async for c in db.conversations.find({"user_id": auth.id})],
        "messages": [_clean(m) async for m in db.messages.find({"user_id": auth.id})],
        "search_history": [_clean(s) async for s in db.search_history.find({"user_id": auth.id})],
        "usage_records": [_clean(r) async for r in db.usage_records.find({"user_id": auth.id})],
        "audit_logs": [_clean(a) async for a in db.audit_logs.find({"actor_id": auth.id})],
    }
    return JSONResponse(
        jsonable_encoder(data, custom_encoder={ObjectId: str}),
        headers={"Content-Disposition": 'attachment; filename="documind-export.json"'},
    )


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(body: DeleteAccountIn, request: Request, auth: AuthUser, db: DB) -> Response:
    """Permanently delete the account. Workspaces where the user is the only member are purged;
    workspaces with other members require transferring ownership first."""
    valid, _ = await verify_password(body.password, auth.user["password_hash"])
    if not valid:
        raise AppError(400, "invalid_credentials", "Password is incorrect")
    blocking, solo = [], []
    async for m in db.memberships.find({"user_id": auth.id, "status": "active"}):
        others = await db.memberships.count_documents({"workspace_id": m["workspace_id"], "user_id": {"$ne": auth.id}, "status": "active"})
        owners = await db.memberships.count_documents({"workspace_id": m["workspace_id"], "role": Role.owner.value, "status": "active"})
        if m["role"] == Role.owner.value and owners == 1 and others:
            blocking.append(str(m["workspace_id"]))
        elif not others:
            solo.append(m["workspace_id"])
    if blocking:
        raise conflict("Transfer ownership of your shared workspaces before deleting your account", "owns_shared_workspaces", {"workspace_ids": blocking})
    store = request.app.state.store
    for ws_id in solo:
        await purge_workspace(db, store, ws_id)
    await db.memberships.delete_many({"user_id": auth.id})
    await db.conversations.delete_many({"user_id": auth.id})
    await db.messages.delete_many({"user_id": auth.id})
    await db.search_history.delete_many({"user_id": auth.id})
    await db.audit_logs.update_many({"actor_id": auth.id}, {"$set": {"actor_id": None}})
    await db.usage_records.update_many({"user_id": auth.id}, {"$set": {"user_id": None}})
    await db.sessions.delete_many({"user_id": auth.id})
    await db.users.delete_one({"_id": auth.id})
    await audit.record(db, action="account.delete", actor_id=None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
