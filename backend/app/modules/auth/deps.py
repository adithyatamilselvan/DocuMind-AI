from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import forbidden, unauthorized
from app.core.ids import utcnow
from app.core.security import csrf_token_for, hash_token, safe_equal

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Endpoints that run before a session exists (or whose only credential is a one-time token).
CSRF_EXEMPT_SUFFIXES = (
    "/auth/register",
    "/auth/login",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/verify-email",
)


@dataclass
class CurrentUser:
    user: dict[str, Any]
    session_token: str

    @property
    def id(self):  # noqa: ANN201
        return self.user["_id"]


def _allowed_origins(settings: Settings) -> set[str]:
    return {settings.frontend_url.rstrip("/"), *(o.rstrip("/") for o in settings.cors_origins)}


async def csrf_protect(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    """Origin check + HMAC double-submit token for cookie-authenticated unsafe requests."""
    if request.method in SAFE_METHODS or request.url.path.endswith(CSRF_EXEMPT_SUFFIXES):
        return
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in _allowed_origins(settings):
        raise forbidden("Cross-origin request blocked")
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        return  # unauthenticated; the auth dependency will reject if required
    header = request.headers.get("x-csrf-token", "")
    expected = csrf_token_for(session_token, settings.secret_key.get_secret_value())
    if not header or not safe_equal(header, expected):
        raise forbidden("Missing or invalid CSRF token")


async def current_user(
    request: Request,
    db: Annotated[AsyncDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise unauthorized()
    session = await db.sessions.find_one(
        {"token_hash": hash_token(token), "expires_at": {"$gt": utcnow()}}
    )
    if not session:
        raise unauthorized("Session expired")
    user = await db.users.find_one({"_id": session["user_id"], "status": "active"})
    if not user:
        raise unauthorized()
    return CurrentUser(user=user, session_token=token)


AuthUser = Annotated[CurrentUser, Depends(current_user)]
DB = Annotated[AsyncDatabase, Depends(get_db)]
