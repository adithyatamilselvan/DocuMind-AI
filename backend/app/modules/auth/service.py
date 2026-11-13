from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.core.email import EmailSender
from app.core.errors import AppError, bad_request, conflict
from app.core.ids import utcnow
from app.core.security import hash_password, hash_token, new_token, verify_password
from app.modules.workspaces import service as ws_service

RESET_TTL = timedelta(hours=1)
VERIFY_TTL = timedelta(days=3)


async def _issue_token(
    db: AsyncDatabase, collection: str, user_id: ObjectId, ttl: timedelta
) -> str:
    token = new_token()
    now = utcnow()
    await db[collection].insert_one(
        {
            "user_id": user_id,
            "token_hash": hash_token(token),
            "expires_at": now + ttl,
            "used_at": None,
            "created_at": now,
        }
    )
    return token


async def send_verification(
    db: AsyncDatabase, settings: Settings, sender: EmailSender, user: dict[str, Any]
) -> None:
    token = await _issue_token(db, "email_verification_tokens", user["_id"], VERIFY_TTL)
    link = f"{settings.frontend_url}/verify-email?token={token}"
    await sender.send(
        user["email"], "Verify your DocuMind email", f"Confirm your email address:\n{link}\n"
    )


async def register(
    db: AsyncDatabase, settings: Settings, sender: EmailSender, email: str, password: str, name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = utcnow()
    user: dict[str, Any] = {
        "email": email.lower(),
        "password_hash": await hash_password(password),
        "name": name,
        "email_verified": False,
        "status": "active",
        "preferences": {"theme": "system", "notifications_email": True},
        "created_at": now,
        "updated_at": now,
    }
    try:
        user["_id"] = (await db.users.insert_one(user)).inserted_id
    except DuplicateKeyError:
        raise conflict("An account with this email already exists", "email_taken") from None
    workspace = await ws_service.create_workspace(db, user["_id"], f"{name}'s workspace")
    await send_verification(db, settings, sender, user)
    return user, workspace


async def authenticate(db: AsyncDatabase, email: str, password: str) -> dict[str, Any]:
    user = await db.users.find_one({"email": email.lower()})
    valid, rehash = await verify_password(password, user["password_hash"] if user else None)
    if not user or not valid or user.get("status") != "active":
        raise AppError(401, "invalid_credentials", "Incorrect email or password")
    if rehash:
        await db.users.update_one(
            {"_id": user["_id"]}, {"$set": {"password_hash": await hash_password(password)}}
        )
    return user


async def create_session(
    db: AsyncDatabase, settings: Settings, user_id: ObjectId, ip: str | None, user_agent: str | None
) -> str:
    token = new_token()
    now = utcnow()
    await db.sessions.insert_one(
        {
            "user_id": user_id,
            "token_hash": hash_token(token),
            "ip": ip,
            "user_agent": (user_agent or "")[:300],
            "created_at": now,
            "expires_at": now + timedelta(hours=settings.session_ttl_hours),
        }
    )
    return token


async def revoke_session(db: AsyncDatabase, token: str) -> None:
    await db.sessions.delete_one({"token_hash": hash_token(token)})


async def revoke_all_sessions(
    db: AsyncDatabase, user_id: ObjectId, except_token: str | None = None
) -> None:
    query: dict[str, Any] = {"user_id": user_id}
    if except_token:
        query["token_hash"] = {"$ne": hash_token(except_token)}
    await db.sessions.delete_many(query)


async def request_password_reset(
    db: AsyncDatabase, settings: Settings, sender: EmailSender, email: str
) -> None:
    user = await db.users.find_one({"email": email.lower(), "status": "active"})
    if not user:
        return  # silent: no account enumeration
    token = await _issue_token(db, "password_reset_tokens", user["_id"], RESET_TTL)
    link = f"{settings.frontend_url}/reset-password?token={token}"
    await sender.send(
        user["email"],
        "Reset your DocuMind password",
        f"Reset your password (valid 1 hour):\n{link}\n",
    )


async def _consume_token(db: AsyncDatabase, collection: str, token: str) -> dict[str, Any]:
    doc = await db[collection].find_one_and_update(
        {"token_hash": hash_token(token), "used_at": None, "expires_at": {"$gt": utcnow()}},
        {"$set": {"used_at": utcnow()}},
    )
    if not doc:
        raise bad_request("This link is invalid or has expired", "invalid_token")
    return doc


async def reset_password(db: AsyncDatabase, token: str, new_password: str) -> None:
    doc = await _consume_token(db, "password_reset_tokens", token)
    await db.users.update_one(
        {"_id": doc["user_id"]},
        {"$set": {"password_hash": await hash_password(new_password), "updated_at": utcnow()}},
    )
    await revoke_all_sessions(db, doc["user_id"])


async def verify_email(db: AsyncDatabase, token: str) -> None:
    doc = await _consume_token(db, "email_verification_tokens", token)
    await db.users.update_one(
        {"_id": doc["user_id"]}, {"$set": {"email_verified": True, "updated_at": utcnow()}}
    )


async def change_password(
    db: AsyncDatabase, user: dict[str, Any], current: str, new: str, keep_token: str
) -> None:
    valid, _ = await verify_password(current, user["password_hash"])
    if not valid:
        raise AppError(400, "invalid_credentials", "Current password is incorrect")
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": await hash_password(new), "updated_at": utcnow()}},
    )
    await revoke_all_sessions(db, user["_id"], except_token=keep_token)
