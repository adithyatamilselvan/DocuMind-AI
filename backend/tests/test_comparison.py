from bson import ObjectId

from app.core.config import get_settings
from app.modules.comparison import service
from app.modules.comparison.schemas import AspectComparison, ComparisonResult, Point
from app.modules.extraction.models import Block, ExtractedDocument, Page

from .conftest import register
from .test_rag_api import setup

OLD = (
    "# Policy\n\nEmployees may work remotely two days per week. Expense claims must be filed within thirty days.\n\n"
    "Offices close at six in the evening on weekdays."
)
NEW = (
    "# Policy\n\nEmployees may work remotely three days per week. Expense claims must be filed within thirty days.\n\n"
    "A new wellbeing allowance of fifty euros per month is available to all staff."
)
SLEEP = "# Study A\n\nThe method used a randomized experiment with controlled sleep schedules. The results show recall decreased by twenty percent."
NAPS = "# Study B\n\nThe method used a survey of students about napping habits. The results show recall increased by five percent."


def doc(*paras):
    return ExtractedDocument([Page(1, [Block("paragraph", t) for t in paras])], "virtual")


def test_diff_finds_added_removed_and_changed_paragraphs():
    d = service.diff_versions(
        doc(
            "Intro stays the same here.",
            "Remote work is allowed two days per week.",
            "Old closing hours apply.",
        ),
        doc(
            "Intro stays the same here.",
            "Remote work is allowed three days per week.",
            "Brand new allowance paragraph.",
        ),
    )
    assert d["stats"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "old_paragraphs": 3,
        "new_paragraphs": 3,
    }
    assert d["changed"][0]["before"].endswith("two days per week.") and d["changed"][0][
        "after"
    ].endswith("three days per week.")
    assert (
        d["added"][0]["text"] == "Brand new allowance paragraph."
        and d["removed"][0]["text"] == "Old closing hours apply."
    )
    assert service.diff_versions(doc("Same."), doc("Same."))["stats"]["changed"] == 0


def test_verify_comparison_drops_unsourced_points_and_unknown_labels():
    sources = {"D1A1S1": {"label": "D1A1S1"}, "D2A1S1": {"label": "D2A1S1"}}
    r = ComparisonResult(
        summary="s",
        aspects=[
            AspectComparison(
                aspect="Methodology",
                similarities=[Point(text="ok", sources=["D1A1S1", "D2A1S1"])],
                differences=[
                    Point(text="fabricated", sources=["D9A9S9"]),
                    Point(text="partly", sources=["D1A1S1", "D9A9S9"]),
                ],
                conflicts=[Point(text="no source at all", sources=[])],
                missing_information=[
                    Point(text="doc 2 omits X", sources=[])
                ],  # allowed without sources
            )
        ],
    )
    out, stats = service.verify_comparison(r, sources)
    a = out["aspects"][0]
    assert [p["text"] for p in a["similarities"]] == ["ok"]
    assert [(p["text"], p["sources"]) for p in a["differences"]] == [("partly", ["D1A1S1"])]
    assert a["conflicts"] == [] and a["missing_information"][0]["text"] == "doc 2 omits X"
    assert stats == {"dropped_points": 2, "removed_labels": 2} and set(out["sources"]) == {
        "D1A1S1",
        "D2A1S1",
    }


async def test_document_comparison_is_grounded_in_retrieved_passages(client, app, ai):
    ws, base, (a, b) = await setup(
        client, app, [("sleep.txt", SLEEP.encode()), ("naps.txt", NAPS.encode())]
    )
    r = await client.post(f"{base}/comparisons", json={"document_ids": [a, b]})
    assert r.status_code == 202 and r.json()["title"] == "sleep vs naps"
    await app.state.queue.drain()
    d = (await client.get(f"{base}/comparisons/{r.json()['id']}")).json()
    assert d["status"] == "completed" and d["kind"] == "documents"
    res = d["result"]
    assert [x["title"] for x in res["documents"]] == ["sleep", "naps"]
    aspects = {x["aspect"]: x for x in res["aspects"]}
    meth = aspects["Methodology"]
    assert any("randomized experiment" in p["text"] for p in meth["differences"]) and any(
        "survey" in p["text"] for p in meth["differences"]
    )
    for aspect in res["aspects"]:
        for point in aspect["similarities"] + aspect["differences"] + aspect["conflicts"]:
            assert point["sources"] and all(s in res["sources"] for s in point["sources"])
    src = res["sources"][meth["differences"][0]["sources"][0]]
    assert src["document_title"] in {"sleep", "naps"} and src["page_number"] == 1 and src["snippet"]
    sbs = {x["aspect"]: x for x in res["side_by_side"]}["Results"]
    assert [c["document_index"] for c in sbs["columns"]] == [1, 2] and all(
        c["passages"] for c in sbs["columns"]
    )


async def test_version_comparison_needs_no_llm_and_summarises_when_available(client, app, ai):
    ws, base, (doc_id,) = await setup(client, app, [("policy.txt", OLD.encode())])
    one = await client.post(f"{base}/comparisons/versions", json={"document_id": doc_id})
    assert one.status_code == 400 and one.json()["error"]["code"] == "single_version"
    await client.post(
        f"{base}/documents/{doc_id}/versions",
        files={"file": ("policy.txt", NEW.encode(), "text/plain")},
    )
    await app.state.queue.drain()
    r = await client.post(f"{base}/comparisons/versions", json={"document_id": doc_id})
    assert r.status_code == 202 and r.json()["title"] == "policy: v1 vs v2"
    await app.state.queue.drain()
    res = (await client.get(f"{base}/comparisons/{r.json()['id']}")).json()["result"]
    assert (
        res["stats"]["changed"] == 1 and res["stats"]["added"] == 1 and res["stats"]["removed"] == 1
    )
    assert "three days" in res["changed"][0]["after"] and res["summary"] and res["notable_changes"]
    assert [v["version_no"] for v in res["versions"]] == [1, 2]
    same = await client.post(
        f"{base}/comparisons/versions",
        json={
            "document_id": doc_id,
            "version_a": (await client.get(f"{base}/documents/{doc_id}/versions")).json()[0]["id"],
            "version_b": (await client.get(f"{base}/documents/{doc_id}/versions")).json()[0]["id"],
        },
    )
    assert same.json()["error"]["code"] == "bad_versions"


async def test_version_diff_still_works_without_llm_key(client, app, hashing, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "fake")
    ws, base, (doc_id,) = await setup(client, app, [("policy.txt", OLD.encode())])
    await client.post(
        f"{base}/documents/{doc_id}/versions",
        files={"file": ("policy.txt", NEW.encode(), "text/plain")},
    )
    await app.state.queue.drain()
    monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")  # no key configured
    r = await client.post(f"{base}/comparisons/versions", json={"document_id": doc_id})
    # consent is not required for the deterministic diff; the AI summary is reported unavailable
    assert r.status_code == 202
    await app.state.queue.drain()
    res = (await client.get(f"{base}/comparisons/{r.json()['id']}")).json()
    assert res["status"] == "completed" and res["result"]["stats"]["changed"] == 1
    assert res["result"]["summary"] is None and "not configured" in res["result"]["summary_note"]


async def test_validation_permissions_isolation_and_cascade(client, new_client, app, ai):
    ws, base, (a, b) = await setup(
        client, app, [("sleep.txt", SLEEP.encode()), ("naps.txt", NAPS.encode())]
    )
    assert (await client.post(f"{base}/comparisons", json={"document_ids": [a]})).status_code == 422
    assert (await client.post(f"{base}/comparisons", json={"document_ids": [a, a]})).json()[
        "error"
    ]["code"] == "too_few_documents"
    assert (
        await client.post(f"{base}/comparisons", json={"document_ids": [a, str(ObjectId())]})
    ).status_code == 404
    rec = (await client.post(f"{base}/comparisons", json={"document_ids": [a, b]})).json()
    await app.state.queue.drain()
    async with new_client() as v:
        await register(v, "v@example.com", "V")
        await client.post(f"{base}/members", json={"email": "v@example.com", "role": "viewer"})
        assert (await v.get(f"{base}/comparisons/{rec['id']}")).status_code == 200
        assert (
            await v.post(f"{base}/comparisons", json={"document_ids": [a, b]})
        ).status_code == 403
    async with new_client() as o:
        await register(o, "o@example.com", "O")
        assert (await o.get(f"{base}/comparisons/{rec['id']}")).status_code == 404
    assert [x["id"] for x in (await client.get(f"{base}/comparisons")).json()] == [rec["id"]]
    await client.delete(f"{base}/documents/{a}")
    assert (await client.get(f"{base}/comparisons/{rec['id']}")).status_code == 404
