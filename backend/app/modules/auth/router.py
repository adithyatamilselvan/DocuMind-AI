import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.rate_limit import client_ip, rate_limit
from app.core.security import csrf_token_for
from app.modules.audit import service as audit
from app.modules.auth import service
from app.modules.auth.deps import DB, AuthUser
from app.modules.auth.schemas import (
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
    VerifyEmailIn,
)
from app.modules.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _set_cookies(response: Response, settings: Settings, token: str) -> None:
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    # Readable by the frontend so it can echo it in X-CSRF-Token.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token_for(token, settings.secret_key.get_secret_value()),
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserOut,
    dependencies=[Depends(rate_limit("register", 10, 3600))],
)
async def register(
    body: RegisterIn, request: Request, response: Response, db: DB, settings: SettingsDep
):
    user, workspace = await service.register(
        db, settings, request.app.state.email, body.email, body.password, body.name
    )
    token = await service.create_session(
        db, settings, user["_id"], client_ip(request), request.headers.get("user-agent")
    )
    _set_cookies(response, settings, token)
    await audit.record(
        db, action="auth.register", actor_id=user["_id"], workspace_id=workspace["_id"],
        ip=client_ip(request),
    )  # fmt: skip
    return UserOut.from_doc(user)


@router.post("/login", response_model=UserOut, dependencies=[Depends(rate_limit("login", 10, 300))])
async def login(body: LoginIn, request: Request, response: Response, db: DB, settings: SettingsDep):
    try:
        user = await service.authenticate(db, body.email, body.password)
    except AppError as e:
        if (
            e.code == "invalid_credentials"
        ):  # no email/password is stored, only a short hash for correlation
            await audit.record(
                db,
                action="auth.login_failed",
                actor_id=None,
                ip=client_ip(request),
                target={"email_hash": hashlib.sha256(body.email.lower().encode()).hexdigest()[:12]},
            )
        raise
    token = await service.create_session(
        db, settings, user["_id"], client_ip(request), request.headers.get("user-agent")
    )
    _set_cookies(response, settings, token)
    await audit.record(db, action="auth.login", actor_id=user["_id"], ip=client_ip(request))
    return UserOut.from_doc(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(auth: AuthUser, response: Response, db: DB, settings: SettingsDep):
    await service.revoke_session(db, auth.session_token)
    _clear_cookies(response, settings)
    await audit.record(db, action="auth.logout", actor_id=auth.id)


@router.get("/me", response_model=UserOut)
async def me(auth: AuthUser):
    return UserOut.from_doc(auth.user)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("forgot", 5, 3600))],
)
async def forgot_password(body: ForgotPasswordIn, request: Request, db: DB, settings: SettingsDep):
    await service.request_password_reset(db, settings, request.app.state.email, body.email)
    return {"status": "accepted"}


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("reset", 10, 3600))],
)
async def reset_password(body: ResetPasswordIn, db: DB):
    await service.reset_password(db, body.token, body.password)


@router.post(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("verify", 20, 3600))],
)
async def verify_email(body: VerifyEmailIn, db: DB):
    await service.verify_email(db, body.token)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("resend", 5, 3600))],
)
async def resend_verification(auth: AuthUser, request: Request, db: DB, settings: SettingsDep):
    if not auth.user.get("email_verified"):
        await service.send_verification(db, settings, request.app.state.email, auth.user)
    return {"status": "accepted"}
