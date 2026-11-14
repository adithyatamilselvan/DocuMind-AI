from bson import ObjectId

from app.core.config import get_settings
from app.modules.extraction.models import Block, ExtractedDocument, Page
from app.modules.insights.evidence import PageIndex
from app.modules.research import service
from app.modules.research.schemas import (
    Contradiction,
    Gap,
    PaperAnalysis,
    PaperItem,
    Synthesis,
    Theme,
)

from .conftest import register
from .test_indexing import upload
from .test_rag_api import setup

PAPER_A = (
    "# Sleep and Memory\n\n"
    "The aim of this study is to investigate whether sleep deprivation reduces memory consolidation. "
    "We conducted a randomized experiment with n = 120 participants over four weeks. "
    "The results show that recall accuracy decreased by twenty percent after sleep deprivation. "
    "We conclude that sleep is essential for memory consolidation in adults. "
    "A limitation of this work is that all participants were university students. "
    "Future work should examine older adults and long term effects."
)
PAPER_B = (
    "# Napping Study\n\n"
    "The objective of this survey is to measure the effect of napping on learning. "
    "We surveyed 300 respondents about their study habits. "
    "The results show that recall accuracy increased by five percent after short naps. "
    "We conclude that napping has a small positive effect. "
    "This study is limited by self reported data."
)

DOC = ExtractedDocument(
    [
        Page(
            1,
            [
                Block(
                    "paragraph",
                    "Recall accuracy decreased by twenty percent after sleep deprivation.",
                )
            ],
        ),
        Page(2, [Block("paragraph", "Naps improve learning.")]),
    ],
    "physical",
)


def test_verify_paper_drops_fabrications_and_flags_gaps():
    from app.modules.insights.schemas import Finding

    a = PaperAnalysis(
        is_research_paper=True,
        objective=Finding(text="o", page=1, quote="Recall accuracy decreased by twenty percent"),
        results=[Finding(text="r", page=1, quote="Profits tripled across the world in one year")],
        potential_gaps=[
            Gap(
                text="g",
                rationale="why",
                evidence=[Finding(text="e", page=9, quote="Naps improve learning")],
            )
        ],
    )
    out, ver = service.verify_paper(a, DOC)
    assert out["objective"]["quote"] and out["results"][0]["quote"] is None
    assert out["potential_gaps"][0]["ai_inferred"] is True
    assert (
        out["potential_gaps"][0]["evidence"][0]["page"] == 2
    )  # real quote, wrong page -> corrected
    assert ver["dropped_quotes"] == 1


def test_verify_synthesis_checks_paper_index_quotes_and_contradictions():
    s = Synthesis(
        overview="o",
        themes=[
            Theme(
                title="t",
                summary="s",
                items=[
                    PaperItem(
                        text="ok",
                        paper=1,
                        page=1,
                        quote="Recall accuracy decreased by twenty percent",
                    ),
                    PaperItem(
                        text="wrong paper", paper=1, page=2, quote="Naps improve learning"
                    ),  # quote is on page 2 of the same doc: fine
                    PaperItem(text="nonexistent paper", paper=7, page=1, quote=None),
                    PaperItem(
                        text="fabricated",
                        paper=2,
                        page=1,
                        quote="Sleep cures every disease known to man",
                    ),
                ],
            )
        ],
        contradictions=[
            Contradiction(
                topic="one-sided", explanation="x", positions=[PaperItem(text="a", paper=1)]
            ),
            Contradiction(
                topic="real",
                explanation="x",
                positions=[PaperItem(text="a", paper=1), PaperItem(text="b", paper=2)],
            ),
        ],
    )
    idx = {1: PageIndex.from_document(DOC), 2: PageIndex.from_document(DOC)}
    out, stats = service.verify_synthesis(s, idx, [{"index": 1}, {"index": 2}])
    items = out["themes"][0]["items"]
    assert [i["paper"] for i in items] == [1, 1, 2] and items[2]["quote"] is None
    assert [c["topic"] for c in out["contradictions"]] == ["real"]
    assert stats["dropped_items"] == 2 and stats["dropped_quotes"] == 1


async def two_papers(client, app):
    return await setup(
        client, app, [("sleep.txt", PAPER_A.encode()), ("nap.txt", PAPER_B.encode())]
    )


async def test_paper_analysis_end_to_end_with_verified_evidence(client, app, ai):
    ws, base, (a, b) = await two_papers(client, app)
    r = await client.post(f"{base}/research/papers", json={"document_id": a})
    assert r.status_code == 202 and r.json()["status"] == "pending"
    await app.state.queue.drain()
    d = (await client.get(f"{base}/research/{r.json()['id']}")).json()
    assert d["status"] == "completed" and d["kind"] == "paper" and d["model"] == "fake-extractive"
    res = d["result"]
    assert res["is_research_paper"] and res["methodology"]["category"] == "experimental"
    assert (
        res["sample_size"]["text"].replace(" ", "") == "n=120" and res["sample_size"]["page"] == 1
    )
    assert (
        "aim of this study" in res["objective"]["quote"] and res["results"] and res["conclusions"]
    )
    assert res["limitations"] and res["future_work"]
    gap = res["potential_gaps"][0]
    assert gap["ai_inferred"] is True and gap["evidence"][0]["quote"]
    assert d["verification"] == {"dropped_quotes": 0, "dropped_pages": 0}


async def test_paper_analysis_is_cached_per_version(client, app, ai, monkeypatch):
    ws, base, (a, _) = await two_papers(client, app)
    first = (await client.post(f"{base}/research/papers", json={"document_id": a})).json()
    await app.state.queue.drain()
    calls = []
    from app.ai import registry

    real = registry.get_llm(get_settings())
    orig = real.structured

    async def counting(*args, **kw):
        calls.append(args[2].__name__)
        return await orig(*args, **kw)

    monkeypatch.setattr(real, "structured", counting)
    second = (await client.post(f"{base}/research/papers", json={"document_id": a})).json()
    await app.state.queue.drain()
    got = (await client.get(f"{base}/research/{second['id']}")).json()
    assert (
        got["status"] == "completed"
        and got["result"] == (await client.get(f"{base}/research/{first['id']}")).json()["result"]
    )
    assert calls == []  # reused, no LLM call


async def test_synthesis_builds_literature_review_from_papers(client, app, ai):
    ws, base, (a, b) = await two_papers(client, app)
    r = await client.post(
        f"{base}/research/synthesis", json={"document_ids": [a, b], "title": "Sleep review"}
    )
    assert r.status_code == 202
    await app.state.queue.drain()
    d = (await client.get(f"{base}/research/{r.json()['id']}")).json()
    assert d["status"] == "completed" and d["title"] == "Sleep review"
    res = d["result"]
    assert [p["title"] for p in res["papers"]] == ["sleep", "nap"] and "sleep" in res["overview"]
    assert [row["paper"] for row in res["comparison_table"]] == [1, 2]
    assert (
        res["comparison_table"][0]["methodology"] == "experimental"
        and res["comparison_table"][1]["methodology"] == "survey"
    )
    theme_items = res["themes"][0]["items"]
    assert {i["paper"] for i in theme_items} == {1, 2} and all(i["quote"] for i in theme_items)
    assert all(g["ai_inferred"] for g in res["research_gaps"])
    # per-paper analyses were created and stored as reusable records
    assert await app.state.db.research_analyses.count_documents({"kind": "paper"}) == 2
    listing = (await client.get(f"{base}/research", params={"kind": "synthesis"})).json()
    assert [x["id"] for x in listing] == [d["id"]] and listing[0]["result"] is None


async def test_validation_permissions_isolation_and_cascade(client, new_client, app, ai):
    ws, base, (a, b) = await two_papers(client, app)
    assert (
        await client.post(f"{base}/research/synthesis", json={"document_ids": [a]})
    ).status_code == 422
    assert (
        await client.post(f"{base}/research/synthesis", json={"document_ids": [a, a]})
    ).status_code in (400, 422)
    assert (
        await client.post(f"{base}/research/papers", json={"document_id": str(ObjectId())})
    ).status_code == 404
    await app.state.db.documents.update_one(
        {"_id": ObjectId(b)}, {"$set": {"status": "PROCESSING"}}
    )
    assert (await client.post(f"{base}/research/synthesis", json={"document_ids": [a, b]})).json()[
        "error"
    ]["code"] == "not_ready"
    await app.state.db.documents.update_one({"_id": ObjectId(b)}, {"$set": {"status": "COMPLETED"}})

    rec = (await client.post(f"{base}/research/papers", json={"document_id": a})).json()
    await app.state.queue.drain()
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "viewer"})
        assert (await v.get(f"{base}/research/{rec['id']}")).status_code == 200
        assert (await v.post(f"{base}/research/papers", json={"document_id": a})).status_code == 403
        assert (await v.delete(f"{base}/research/{rec['id']}")).status_code == 403
    async with new_client() as o:
        await register(o, "o@example.com", "O")
        assert (await o.get(f"{base}/research/{rec['id']}")).status_code == 404
        assert (await o.get(f"{base}/research")).status_code == 404
    # deleting the source document removes analyses derived from it
    await client.delete(f"{base}/documents/{a}")
    assert (await client.get(f"{base}/research/{rec['id']}")).status_code == 404
    assert await app.state.db.research_analyses.count_documents({"document_ids": ObjectId(a)}) == 0


async def test_unavailable_without_llm_key(client, app, hashing, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")
    ws, base, (a, _) = await two_papers(client, app)
    r = await client.post(f"{base}/research/papers", json={"document_id": a})
    assert r.status_code == 202
    await app.state.queue.drain()
    d = (await client.get(f"{base}/research/{r.json()['id']}")).json()
    assert d["status"] == "unavailable" and "not configured" in d["error"]


_ = upload
