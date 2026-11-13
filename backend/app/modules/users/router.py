from fastapi import APIRouter, Response, status

from app.core.ids import utcnow
from app.modules.auth import service as auth_service
from app.modules.auth.deps import DB, AuthUser
from app.modules.auth.schemas import ChangePasswordIn
from app.modules.users.schemas import UpdateProfileIn, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
async def update_profile(body: UpdateProfileIn, auth: AuthUser, db: DB):
    patch: dict = {"updated_at": utcnow()}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.preferences is not None:
        patch["preferences"] = body.preferences.model_dump()
    user = await db.users.find_one_and_update(
        {"_id": auth.id}, {"$set": patch}, return_document=True
    )
    return UserOut.from_doc(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordIn, auth: AuthUser, db: DB) -> Response:
    await auth_service.change_password(
        db, auth.user, body.current_password, body.new_password, auth.session_token
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
