"""Opt-in integration test with a REAL embedding model (no paid API): `pytest -m integration`.

Downloads sentence-transformers/all-MiniLM-L6-v2 (~90 MB) on first run. Questions are paraphrases that share
(almost) no keywords with the documents, so only genuine semantic retrieval can pass."""

import pytest

from app.core.config import get_settings

from .conftest import enable_ai, first_workspace, register
from .test_indexing import upload

pytestmark = pytest.mark.integration

DOCS = {
    "annual-report": "Quarterly revenue grew twelve percent in Europe, driven by strong demand for the new product line. Operating margin improved as logistics costs fell.",
    "cell-biology": "Mitochondria generate most of the cell's supply of adenosine triphosphate, which stores chemical energy. Chloroplasts convert light into glucose.",
    "solar-system": "Jupiter is the largest planet and has a Great Red Spot, a storm that has lasted for centuries. Mars has the tallest volcano, Olympus Mons.",
    "service-agreement": "Either party may terminate this agreement with thirty days written notice. The supplier's total liability is limited to the fees paid in the preceding twelve months.",
    "sourdough-guide": "A sourdough starter is a fermented culture of flour and water containing wild yeast. Feed the starter daily and keep it at room temperature.",
}
QUESTIONS = [
    ("How much did sales increase on the European market?", "annual-report"),
    ("Which part of a cell makes power for the organism?", "cell-biology"),
    ("Which world has a giant lasting storm?", "solar-system"),
    ("Can I end the contract early, and how much warning is required?", "service-agreement"),
    ("How do I look after a bread culture?", "sourdough-guide"),
]


async def test_real_semantic_retrieval_through_the_full_pipeline(client, app, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "embedding_provider", "local")
    monkeypatch.setattr(s, "embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setattr(s, "embedding_dim", 384)
    monkeypatch.setattr(s, "llm_provider", "fake")
    await register(client)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    base = f"/api/v1/workspaces/{ws['id']}"
    for title, text in DOCS.items():
        await upload(client, base, f"{title}.txt", text.encode())
    await app.state.queue.drain()
    statuses = {d["title"]: d["status"] for d in (await client.get(f"{base}/documents")).json()["items"]}
    assert set(statuses.values()) == {"COMPLETED"}, statuses
    chunk = await app.state.db.document_chunks.find_one({})
    assert chunk["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2" and len(chunk["embedding"]) == 384

    hits_top1 = 0
    for question, expected in QUESTIONS:
        r = await client.post(f"{base}/search", json={"query": question, "mode": "semantic", "limit": 3})
        assert r.status_code == 200, r.text
        top = [h["document_title"] for h in r.json()["hits"]]
        print(f"{question!r} -> {top}")
        hits_top1 += top[:1] == [expected]
    assert hits_top1 >= 4, f"only {hits_top1}/5 paraphrased questions retrieved the right document first"
