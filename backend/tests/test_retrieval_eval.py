"""Retrieval quality regression guard on the labelled sample corpus (offline embedder)."""

from app.core.config import get_settings
from evals.datasets import CORPUS, QUESTIONS
from evals.retrieval_eval import evaluate

from .conftest import enable_ai, first_workspace, register
from .test_indexing import upload


async def test_retrieval_metrics_on_sample_corpus(client, app, hashing, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")
    await register(client)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    base = f"/api/v1/workspaces/{ws['id']}"
    for title, text in CORPUS.items():
        await upload(client, base, f"{title}.txt", text.encode())
    await app.state.queue.drain()

    async def search(question: str, mode: str) -> list[str]:
        r = await client.post(f"{base}/search", json={"query": question, "mode": mode, "limit": 10})
        assert r.status_code == 200, r.text
        return [h["document_title"] for h in r.json()["hits"]]

    results = {m: await evaluate(search, QUESTIONS, m) for m in ("semantic", "keyword", "hybrid")}
    for m, r in results.items():
        print(f"\n{m:9s} R@1={r.recall_at_1:.2f} R@3={r.recall_at_3:.2f} R@5={r.recall_at_5:.2f} "
              f"MRR={r.mrr:.2f} latency={r.mean_latency_ms:.0f}ms misses={r.misses}")  # fmt: skip
    hybrid = results["hybrid"]
    assert hybrid.recall_at_3 >= 0.9, hybrid.misses
    assert hybrid.mrr >= 0.8
    # hybrid must not be worse than the weaker single mode
    assert hybrid.mrr >= min(results["semantic"].mrr, results["keyword"].mrr)
