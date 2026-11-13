from bson import ObjectId

from app.ai.providers.embeddings import build_embedder
from app.core.config import get_settings
from app.modules.ingestion.errors import RetryableError
from app.modules.ingestion.orchestrator import RetryLater, run_job
from app.modules.vector_search import atlas
from app.modules.vector_search.base import Scope
from app.modules.vector_search.definitions import (
    TEXT_INDEX,
    VECTOR_INDEX,
    text_index_definition,
    vector_index_definition,
)
from app.modules.vector_search.local import LocalVectorStore

from .conftest import enable_ai, first_workspace, register
from .helpers import make_docx, make_pdf

FINANCE = (
    "Quarterly revenue grew twelve percent in Europe, driven by strong demand for the new product line. "
    "Operating margin improved as logistics costs fell during the second half of the year. "
) * 4
BIOLOGY = (
    "Mitochondria generate most of the cell's supply of adenosine triphosphate, which stores chemical "
    "energy. Photosynthesis in chloroplasts converts light into glucose through the Calvin cycle. "
) * 4


async def upload(client, base, name, data):
    r = await client.post(
        f"{base}/documents/upload", files=[("files", (name, data, "application/octet-stream"))]
    )
    return r.json()["results"][0]["document"]["id"]


async def workspace(client, email="a@example.com"):
    await register(client, email)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    return ws, f"/api/v1/workspaces/{ws['id']}"


async def search(app, ws_id, query, mode="vector", doc_ids=None, k=5):
    s = get_settings()
    store, db = app.state.vectors, app.state.db
    scope = Scope(workspace_id=ObjectId(ws_id), document_ids=doc_ids)
    if mode == "vector":
        qv = await build_embedder(s).embed_query(query)
        return await store.vector_search(db, qv, scope, k)
    return await store.keyword_search(db, query, scope, k)


async def test_full_pipeline_indexes_chunks_with_provenance(client, app, hashing):
    ws, base = await workspace(client)
    pdf = make_pdf(
        [{"heading": "Financials", "body": FINANCE}, {"heading": "Biology", "body": BIOLOGY}]
    )
    doc_id = await upload(client, base, "report.pdf", pdf)
    await app.state.queue.drain()
    d = (await client.get(f"{base}/documents/{doc_id}")).json()
    assert d["status"] == "COMPLETED", d
    chunks = [c async for c in app.state.db.document_chunks.find({"document_id": ObjectId(doc_id)})]
    assert chunks and all(c["is_current"] and len(c["embedding"]) == 1024 for c in chunks)
    c0 = chunks[0]
    for field in ("workspace_id", "document_id", "document_version_id", "chunk_id", "chunk_index", "content",
                  "page_number", "section_heading", "token_count", "embedding_model", "embedding_version", "metadata"):  # fmt: skip
        assert field in c0, field
    assert c0["embedding_model"] == "hashing-bow" and c0["workspace_id"] == ObjectId(ws["id"])
    assert {c["page_number"] for c in chunks} == {1, 2}
    assert {c["section_heading"] for c in chunks if c["page_number"] == 2} == {"Biology"}
    usage = await app.state.db.usage_records.find_one({"kind": "embedding"})
    assert usage and usage["tokens_in"] > 0 and "content" not in str(usage)


async def test_semantic_and_keyword_search_return_the_right_pages(client, app, hashing):
    ws, base = await workspace(client)
    doc_id = await upload(
        client,
        base,
        "r.pdf",
        make_pdf(
            [{"heading": "Financials", "body": FINANCE}, {"heading": "Biology", "body": BIOLOGY}]
        ),
    )
    await app.state.queue.drain()
    hits = await search(app, ws["id"], "how did European revenue develop")
    assert (
        hits[0].chunk["page_number"] == 1
        and hits[0].source == "vector"
        and "embedding" not in hits[0].chunk
    )
    bio = await search(app, ws["id"], "mitochondria energy photosynthesis")
    assert bio[0].chunk["page_number"] == 2
    kw = await search(app, ws["id"], "Calvin cycle", mode="keyword")
    assert kw and kw[0].chunk["page_number"] == 2 and kw[0].source == "keyword"
    assert (await search(app, ws["id"], "zzzxqnonexistent", mode="keyword")) == []
    assert all(h.chunk["document_id"] == ObjectId(doc_id) for h in hits)


async def test_tenant_isolation_and_document_scope(client, new_client, app, hashing):
    ws_a, base_a = await workspace(client, "a@example.com")
    doc_a = await upload(client, base_a, "a.docx", make_docx([("Normal", FINANCE)]))
    doc_a2 = await upload(client, base_a, "b.docx", make_docx([("Normal", BIOLOGY)]))
    async with new_client() as other:
        ws_b, base_b = await workspace(other, "b@example.com")
        await upload(
            other, base_b, "b.docx", make_docx([("Normal", FINANCE + " Bob's private forecast.")])
        )
        await app.state.queue.drain()
        for mode in ("vector", "keyword"):
            a_hits = await search(app, ws_a["id"], "revenue forecast", mode=mode)
            b_hits = await search(app, ws_b["id"], "revenue forecast", mode=mode)
            assert a_hits and b_hits
            assert {h.chunk["workspace_id"] for h in a_hits} == {ObjectId(ws_a["id"])}
            assert {h.chunk["workspace_id"] for h in b_hits} == {ObjectId(ws_b["id"])}
    only = await search(app, ws_a["id"], "revenue", doc_ids=[ObjectId(doc_a2)])
    assert {h.chunk["document_id"] for h in only} == {ObjectId(doc_a2)}
    assert await search(app, ws_a["id"], "revenue", doc_ids=[]) == []
    assert doc_a != doc_a2


async def test_deleted_document_is_not_retrievable(client, app, hashing):
    ws, base = await workspace(client)
    doc_id = await upload(client, base, "a.docx", make_docx([("Normal", FINANCE)]))
    await app.state.queue.drain()
    assert await search(app, ws["id"], "revenue growth")
    assert (await client.delete(f"{base}/documents/{doc_id}")).status_code == 204
    assert await search(app, ws["id"], "revenue growth") == []
    assert await search(app, ws["id"], "revenue growth", mode="keyword") == []
    assert await app.state.db.document_chunks.count_documents({}) == 0


async def test_new_version_replaces_old_chunks_atomically(client, app, hashing):
    ws, base = await workspace(client)
    doc_id = await upload(client, base, "a.docx", make_docx([("Normal", FINANCE)]))
    await app.state.queue.drain()
    v1 = await app.state.db.document_chunks.count_documents({"document_id": ObjectId(doc_id)})
    r = await client.post(
        f"{base}/documents/{doc_id}/versions",
        files={"file": ("a.docx", make_docx([("Normal", BIOLOGY)]), "x")},
    )
    assert r.json()["outcome"] == "created"
    await app.state.queue.drain()
    chunks = [c async for c in app.state.db.document_chunks.find({"document_id": ObjectId(doc_id)})]
    assert v1 > 0 and chunks and len({c["document_version_id"] for c in chunks}) == 1
    assert "mitochondria" in " ".join(c["content"] for c in chunks).lower()
    assert "revenue" not in " ".join(c["content"] for c in chunks).lower()


async def test_embedding_resume_only_embeds_missing_chunks(client, app, hashing, monkeypatch):
    ws, base = await workspace(client)
    s = app.state.queue._settings
    calls: list[int] = []
    real = build_embedder(s)
    orig = real.embed_documents

    state = {"fail": True}

    async def flaky(texts):
        calls.append(len(texts))
        if state["fail"] and len(calls) == 2:
            raise RetryableError("provider hiccup")
        return await orig(texts)

    class Wrapped:
        name, model, dimensions, version = real.name, real.model, real.dimensions, real.version
        max_batch = 2
        embed_documents = staticmethod(flaky)
        embed_query = staticmethod(real.embed_query)

    monkeypatch.setattr("app.modules.ingestion.chunk_stages.build_embedder", lambda s: Wrapped)
    text = "\n\n".join(f"Paragraph {i} " + FINANCE[:900] for i in range(6))
    doc_id = await upload_held(client, app, base, "a.txt", text.encode())
    job = await app.state.db.processing_jobs.find_one({"document_id": ObjectId(doc_id)})
    try:
        await run_job(app.state.db, s, app.state.store, job["_id"])
        raised = False
    except RetryLater:
        raised = True
    assert raised
    embedded = await app.state.db.document_chunks.count_documents(
        {"document_id": ObjectId(doc_id), "embedding": {"$ne": None}}
    )
    total = await app.state.db.document_chunks.count_documents({"document_id": ObjectId(doc_id)})
    assert 0 < embedded < total
    state["fail"] = False
    calls.clear()
    await run_job(app.state.db, s, app.state.store, job["_id"])
    assert sum(calls) == total - embedded  # only the missing ones
    assert (await app.state.db.documents.find_one({"_id": ObjectId(doc_id)}))[
        "status"
    ] == "COMPLETED"


async def upload_held(client, app, base, name, data):
    class Hold:
        async def enqueue(self, job_id):
            return None

        async def close(self):
            return None

    real = app.state.queue
    app.state.queue = Hold()
    try:
        return await upload(client, base, name, data)
    finally:
        app.state.queue = real


async def test_consent_withdrawn_before_embedding_fails_without_calling_provider(
    client, app, monkeypatch
):
    s = get_settings()
    monkeypatch.setattr(s, "embedding_provider", "openai")
    ws, base = await workspace(client)
    doc_id = await upload_held(client, app, base, "a.txt", FINANCE.encode())
    await client.patch(
        f"/api/v1/workspaces/{ws['id']}", json={"settings": {"ai_processing_consent": False}}
    )
    job = await app.state.db.processing_jobs.find_one({"document_id": ObjectId(doc_id)})
    await run_job(app.state.db, s, app.state.store, job["_id"])
    d = await app.state.db.documents.find_one({"_id": ObjectId(doc_id)})
    assert d["status"] == "FAILED" and "not enabled" in d["error"]


async def test_index_stage_waits_when_search_index_not_ready(client, app, hashing, monkeypatch):
    ws, base = await workspace(client)

    class NotReady:
        async def health(self, db):
            return {"ready": False}

    monkeypatch.setattr(
        "app.modules.ingestion.chunk_stages.build_vector_store", lambda s: NotReady()
    )
    doc_id = await upload_held(client, app, base, "a.txt", FINANCE.encode())
    job = await app.state.db.processing_jobs.find_one({"document_id": ObjectId(doc_id)})
    try:
        await run_job(app.state.db, app.state.queue._settings, app.state.store, job["_id"])
        raise AssertionError("expected RetryLater")
    except RetryLater:
        pass
    # chunks exist but are NOT searchable until the index is verified
    assert await search(app, ws["id"], "revenue") == []


async def test_local_store_ignores_chunks_with_other_dimensions(client, app):
    db = app.state.db
    wid = ObjectId()

    def row(i, vec, current, content):
        return {
            "workspace_id": wid, "document_id": ObjectId(), "document_version_id": ObjectId(),
            "chunk_index": i, "chunk_id": f"x:{i}", "is_current": current, "embedding": vec,
            "content": content,
        }  # fmt: skip

    await db.document_chunks.insert_many([
        row(0, [1.0, 0.0, 0.0], True, "ok"),
        row(1, [1.0, 0.0], True, "other model"),
        row(2, [1.0, 0.0, 0.0], False, "stale"),
    ])  # fmt: skip
    hits = await LocalVectorStore(100).vector_search(db, [1.0, 0.0, 0.0], Scope(wid), 5)
    assert [h.chunk["content"] for h in hits] == ["ok"] and abs(hits[0].score - 1.0) < 1e-6


# ---------- Atlas query shapes (captured, since no Atlas cluster is available here) ----------


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def gen():
            for r in self.rows:
                yield r

        return gen()


class _FakeColl:
    def __init__(self, rows=(), indexes=()):
        self.pipelines, self.rows, self.indexes = [], list(rows), list(indexes)

    async def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return _Cursor([dict(r) for r in self.rows])

    async def list_search_indexes(self):
        return _Cursor(self.indexes)


class _FakeDb:
    def __init__(self, coll):
        self.document_chunks = coll


async def test_atlas_vector_pipeline_is_tenant_filtered():
    coll = _FakeColl([{"content": "x", "score": 0.9}])
    store = atlas.AtlasVectorStore(get_settings())
    wid, d1 = ObjectId(), ObjectId()
    hits = await store.vector_search(_FakeDb(coll), [0.1] * 4, Scope(wid, [d1]), 8)
    vs = coll.pipelines[0][0]["$vectorSearch"]
    assert vs["index"] == VECTOR_INDEX and vs["path"] == "embedding" and vs["limit"] == 8
    assert vs["numCandidates"] >= 8 * 10
    assert vs["filter"] == {"workspace_id": wid, "is_current": True, "document_id": {"$in": [d1]}}
    assert coll.pipelines[0][-1] == {"$project": {"embedding": 0}} and hits[0].score == 0.9


async def test_atlas_keyword_pipeline_is_tenant_filtered():
    coll = _FakeColl([{"content": "x", "score": 3.1}])
    wid, d1 = ObjectId(), ObjectId()
    await atlas.AtlasVectorStore(get_settings()).keyword_search(
        _FakeDb(coll), "calvin cycle", Scope(wid, [d1]), 5
    )
    s = coll.pipelines[0][0]["$search"]
    assert s["index"] == TEXT_INDEX
    filters = s["compound"]["filter"]
    assert {"equals": {"path": "workspace_id", "value": wid}} in filters
    assert {"equals": {"path": "is_current", "value": True}} in filters
    assert {"in": {"path": "document_id", "value": [d1]}} in filters


async def test_atlas_health_verifies_indexes_instead_of_assuming():
    store = atlas.AtlasVectorStore(get_settings())
    ok = _FakeColl(
        indexes=[
            {"name": VECTOR_INDEX, "queryable": True, "status": "READY"},
            {"name": TEXT_INDEX, "queryable": True, "status": "READY"},
        ]
    )
    assert (await store.health(_FakeDb(ok)))["ready"] is True
    building = _FakeColl(indexes=[{"name": VECTOR_INDEX, "queryable": False, "status": "BUILDING"}])
    h = await store.health(_FakeDb(building))
    assert h["ready"] is False and h["indexes"][TEXT_INDEX]["exists"] is False


def test_index_definitions_match_embedding_dimension_and_filter_fields():
    d = vector_index_definition(1024)["fields"]
    assert d[0] == {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1024,
        "similarity": "cosine",
    }
    assert {f["path"] for f in d if f["type"] == "filter"} == {
        "workspace_id",
        "document_id",
        "is_current",
    }
    assert text_index_definition()["mappings"]["fields"]["workspace_id"] == {"type": "objectId"}
