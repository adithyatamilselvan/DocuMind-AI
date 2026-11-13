from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.modules.auth.deps import AuthUser

router = APIRouter(prefix="/system", tags=["system"])


class ClientConfig(BaseModel):
    max_upload_mb: int
    max_files_per_upload: int
    allowed_extensions: list[str]
    external_ai_processing: bool


@router.get("/config", response_model=ClientConfig)
async def client_config(_: AuthUser, settings: Annotated[Settings, Depends(get_settings)]):
    """Non-secret settings the UI needs (limits, whether documents leave the server for AI)."""
    return ClientConfig(
        max_upload_mb=settings.max_upload_mb,
        max_files_per_upload=settings.max_files_per_upload,
        allowed_extensions=["pdf", "docx", "txt"],
        external_ai_processing=settings.ai_external,
    )
