import os

os.environ.update(
    APP_ENV="test",
    APP_SECRET_KEY="test-secret-key-test-secret-key-test-secret-key",
    MONGODB_DB="documind_test",
    EMAIL_BACKEND="log",
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
