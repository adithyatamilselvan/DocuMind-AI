import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import create_client
from app.core.email import build_email_sender
from app.core.errors import install_error_handlers
from app.core.indexes import ensure_indexes
from app.middleware.request_id import RequestIdMiddleware

log = logging.getLogger("documind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = create_client(settings)
    app.state.client = client
    app.state.db = client[settings.mongodb_db]
    app.state.email = build_email_sender(settings)
    await client.admin.command("ping")
    await ensure_indexes(app.state.db)
    log.info(
        "Started env=%s db=%s vector_backend=%s",
        settings.env,
        settings.mongodb_db,
        settings.vector_backend,
    )
    try:
        yield
    finally:
        await client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DocuMind AI API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.env == "production" else "/docs",
        redoc_url=None,
    )
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    async def health():
        await app.state.db.command("ping")
        return {"status": "ok"}

    return app


app = create_app()
