from fastapi import APIRouter, Depends

from app.modules.auth.deps import csrf_protect
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.workspaces.router import router as workspaces_router

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_protect)])
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(workspaces_router)
