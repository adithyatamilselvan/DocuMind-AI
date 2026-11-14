import os

os.environ.update(
    APP_ENV="test",
    APP_SECRET_KEY="test-secret-key-test-secret-key-test-secret-key",
    MONGODB_DB="documind_test",
    EMAIL_BACKEND="log",
    MAX_UPLOAD_MB="1",
    LOCAL_STORAGE_DIR=".local-data/test-objects",
    JOB_BACKEND="inline",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture(autouse=True)
async def clean_db(app):
    limiter.reset()
    db = app.state.db
    for name in await db.list_collection_names():
        await db[name].delete_many({})
    yield


def make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def client(app):
    async with make_client(app) as c:
        yield c


@pytest.fixture
def new_client(app):
    """Factory for additional independent clients (separate cookie jars)."""
    return lambda: make_client(app)


async def register(c: httpx.AsyncClient, email: str = "a@example.com", name: str = "Alice"):
    r = await c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-9", "name": name},
    )
    assert r.status_code == 201, r.text
    c.headers["X-CSRF-Token"] = c.cookies.get("documind_csrf")
    return r.json()


async def first_workspace(c: httpx.AsyncClient) -> dict:
    r = await c.get("/api/v1/workspaces")
    assert r.status_code == 200
    return r.json()[0]


async def enable_ai(c: httpx.AsyncClient, ws_id: str) -> None:
    r = await c.patch(
        f"/api/v1/workspaces/{ws_id}", json={"settings": {"ai_processing_consent": True}}
    )
    assert r.status_code == 200


@pytest.fixture
def fake_stages():
    """Replace the pipeline stages with controllable fakes; restores the originals afterwards."""
    from app.modules.documents.states import DocumentStatus as S
    from app.modules.ingestion import orchestrator as o

    calls: list[str] = []

    def make(name, status, fail=None):
        async def run(ctx):
            calls.append(name)
            if fail and fail.get("times", 0) > 0:
                fail["times"] -= 1
                raise fail["exc"]

        return o.Stage(name, status, run)

    saved = list(o.STAGES)
    o.STAGES.clear()

    class Fakes:
        pass

    f = Fakes()
    f.calls = calls
    f.make = make
    f.set = lambda *stages: (o.STAGES.clear(), o.STAGES.extend(stages))
    f.default = lambda **fails: f.set(
        make("extract", S.EXTRACTING, fails.get("extract")),
        make("chunk", S.CHUNKING, fails.get("chunk")),
        make("embed", S.EMBEDDING, fails.get("embed")),
        make("index", S.INDEXING, fails.get("index")),
    )
    yield f
    o.STAGES.clear()
    o.STAGES.extend(saved)


@pytest.fixture
def hashing(monkeypatch):
    """Use the deterministic test embedder (no network, no consent needed) and the local vector store."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_provider", "hashing")
    yield


@pytest.fixture
def ai(monkeypatch, hashing):
    """Hashing embeddings + extractive fake LLM: no network, deterministic."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "fake")
