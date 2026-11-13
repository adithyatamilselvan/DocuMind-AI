import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import create_client
from app.core.email import build_email_sender
from app.core.errors import install_error_handlers
from app.core.indexes import ensure_indexes
from app.middleware.request_id import RequestIdMiddleware
from app.modules.ingestion.queue import build_queue, recover_stuck_jobs
from app.modules.ingestion.stages import register_default_stages
from app.modules.vector_search.factory import build_vector_store
from app.storage.factory import build_object_store

log = logging.getLogger("documind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = create_client(settings)
    app.state.client = client
    app.state.db = client[settings.mongodb_db]
    app.state.email = build_email_sender(settings)
    app.state.store = build_object_store(settings)
    app.state.queue = build_queue(app.state.db, settings, app.state.store)
    app.state.vectors = build_vector_store(settings)
    register_default_stages()
    await client.admin.command("ping")
    await ensure_indexes(app.state.db)
    if settings.job_backend == "inline" and settings.env != "test":
        # Inline jobs die with the process: pick up anything left unfinished.
        await recover_stuck_jobs(app.state.db, app.state.queue, timedelta(seconds=0))
    log.info(
        "Started env=%s db=%s vector_backend=%s",
        settings.env,
        settings.mongodb_db,
        settings.vector_backend,
    )
    try:
        yield
    finally:
        await app.state.queue.close()
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

    @app.get("/health/ready", tags=["system"])
    async def ready():
        """Readiness: database reachable AND the search indexes verified (not assumed)."""
        from fastapi.responses import JSONResponse

        await app.state.db.command("ping")
        vec = await app.state.vectors.health(app.state.db)
        return JSONResponse(
            {"status": "ok" if vec["ready"] else "degraded", "search": vec},
            status_code=200 if vec["ready"] else 503,
        )

    return app


app = create_app()
