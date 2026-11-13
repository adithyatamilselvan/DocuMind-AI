import re
import secrets
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.ids import utcnow
from app.modules.workspaces.roles import Role


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


async def create_workspace(db: AsyncDatabase, owner_id: ObjectId, name: str) -> dict[str, Any]:
    now = utcnow()
    ws: dict[str, Any] = {
        "name": name.strip(),
        "slug": _slugify(name),
        "owner_id": owner_id,
        "settings": {"ai_processing_consent": False},
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    ws["_id"] = (await db.workspaces.insert_one(ws)).inserted_id
    try:
        await db.memberships.insert_one(
            {
                "workspace_id": ws["_id"],
                "user_id": owner_id,
                "role": Role.owner.value,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
    except Exception:
        await db.workspaces.delete_one({"_id": ws["_id"]})
        raise
    return ws


async def list_for_user(db: AsyncDatabase, user_id: ObjectId) -> list[tuple[dict[str, Any], Role]]:
    memberships = {
        m["workspace_id"]: Role(m["role"])
        async for m in db.memberships.find({"user_id": user_id, "status": "active"})
    }
    if not memberships:
        return []
    out = []
    async for ws in db.workspaces.find(
        {"_id": {"$in": list(memberships)}, "deleted_at": None}
    ).sort("created_at", 1):
        out.append((ws, memberships[ws["_id"]]))
    return out


async def update_workspace(
    db: AsyncDatabase, workspace_id: ObjectId, name: str | None, settings: dict[str, Any] | None
) -> dict[str, Any]:
    patch: dict[str, Any] = {"updated_at": utcnow()}
    if name is not None:
        patch["name"] = name.strip()
    if settings is not None:
        for k, v in settings.items():
            patch[f"settings.{k}"] = v
    ws = await db.workspaces.find_one_and_update(
        {"_id": workspace_id, "deleted_at": None}, {"$set": patch}, return_document=True
    )
    if not ws:
        raise not_found("Workspace not found")
    return ws


async def soft_delete_workspace(db: AsyncDatabase, workspace_id: ObjectId) -> None:
    await db.workspaces.update_one(
        {"_id": workspace_id}, {"$set": {"deleted_at": utcnow(), "updated_at": utcnow()}}
    )


async def list_members(db: AsyncDatabase, workspace_id: ObjectId) -> list[dict[str, Any]]:
    members = [
        m async for m in db.memberships.find({"workspace_id": workspace_id, "status": "active"})
    ]
    users = {
        u["_id"]: u async for u in db.users.find({"_id": {"$in": [m["user_id"] for m in members]}})
    }
    return [
        {
            "user_id": m["user_id"],
            "email": users[m["user_id"]]["email"],
            "name": users[m["user_id"]]["name"],
            "role": m["role"],
            "joined_at": m["created_at"],
        }
        for m in members
        if m["user_id"] in users
    ]


async def _owner_count(db: AsyncDatabase, workspace_id: ObjectId) -> int:
    return await db.memberships.count_documents(
        {"workspace_id": workspace_id, "role": Role.owner.value, "status": "active"}
    )


async def add_member(
    db: AsyncDatabase, workspace_id: ObjectId, actor_role: Role, email: str, role: Role
) -> dict[str, Any]:
    if role == Role.owner and actor_role != Role.owner:
        raise forbidden("Only an owner can grant the owner role")
    user = await db.users.find_one({"email": email.lower(), "status": "active"})
    if not user:
        # Email invitations for non-registered users are not implemented yet.
        raise not_found("No registered user with that email. Ask them to sign up first.")
    now = utcnow()
    try:
        await db.memberships.insert_one(
            {
                "workspace_id": workspace_id,
                "user_id": user["_id"],
                "role": role.value,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
    except DuplicateKeyError:
        raise conflict("User is already a member of this workspace") from None
    return {
        "user_id": user["_id"],
        "email": user["email"],
        "name": user["name"],
        "role": role.value,
        "joined_at": now,
    }


async def change_member_role(
    db: AsyncDatabase, workspace_id: ObjectId, actor_role: Role, user_id: ObjectId, role: Role
) -> None:
    target = await db.memberships.find_one(
        {"workspace_id": workspace_id, "user_id": user_id, "status": "active"}
    )
    if not target:
        raise not_found("Member not found")
    current = Role(target["role"])
    if (role == Role.owner or current == Role.owner) and actor_role != Role.owner:
        raise forbidden("Only an owner can change owner roles")
    if current == Role.owner and role != Role.owner and await _owner_count(db, workspace_id) <= 1:
        raise bad_request("A workspace must keep at least one owner", "last_owner")
    await db.memberships.update_one(
        {"_id": target["_id"]}, {"$set": {"role": role.value, "updated_at": utcnow()}}
    )


async def remove_member(
    db: AsyncDatabase,
    workspace_id: ObjectId,
    actor_role: Role,
    actor_id: ObjectId,
    user_id: ObjectId,
) -> None:
    target = await db.memberships.find_one(
        {"workspace_id": workspace_id, "user_id": user_id, "status": "active"}
    )
    if not target:
        raise not_found("Member not found")
    current = Role(target["role"])
    leaving = user_id == actor_id
    if not leaving and not actor_role.at_least(Role.admin):
        raise forbidden()
    if current == Role.owner and not leaving and actor_role != Role.owner:
        raise forbidden("Only an owner can remove an owner")
    if current == Role.owner and await _owner_count(db, workspace_id) <= 1:
        raise bad_request("A workspace must keep at least one owner", "last_owner")
    await db.memberships.delete_one({"_id": target["_id"]})
