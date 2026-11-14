from fastapi import APIRouter, Depends

from app.api.v1.system import router as system_router
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.deps import csrf_protect
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.collections.router import router as collections_router
from app.modules.documents.router import router as documents_router
from app.modules.documents.transfer_router import router as transfer_router
from app.modules.insights.router import router as insights_router
from app.modules.rag.router import router as rag_router
from app.modules.users.router import router as users_router
from app.modules.workspaces.router import router as workspaces_router

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(csrf_protect)])
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(workspaces_router)
api_router.include_router(transfer_router)
api_router.include_router(documents_router)
api_router.include_router(collections_router)
api_router.include_router(analytics_router)
api_router.include_router(system_router)
api_router.include_router(rag_router)
api_router.include_router(chat_router)
api_router.include_router(insights_router)
