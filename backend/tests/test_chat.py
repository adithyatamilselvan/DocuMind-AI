import json

import pytest

from app.ai.errors import LLMError
from app.core.config import get_settings
from app.modules.rag.deps import llm_dep

from .conftest import first_workspace, register
from .test_rag_api import FIN_BIO, Scripted, setup


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def convo(client, base, **body):
    r = await client.post(f"{base}/conversations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def send(client, base, cid, text):
    r = await client.post(f"{base}/conversations/{cid}/messages", json={"content": text})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert (
        r.headers["cache-control"].startswith("no-cache") and r.headers["x-accel-buffering"] == "no"
    )
    return parse_sse(r.text)


async def test_streaming_turn_persists_messages_and_validated_citations(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    c = await convo(client, base)
    events = await send(
        client, base, c["id"], "How did operating margin and logistics costs change?"
    )
    kinds = [k for k, _ in events]
    assert kinds[0] == "user_message" and "title" in kinds and "retrieval" in kinds
    assert (
        kinds.index("retrieval") < kinds.index("final") < kinds.index("done")
        and kinds[-1] == "done"
    )
    final = next(d for k, d in events if k == "final")
    assert final["grounded"] and final["citations"][0]["document_id"] == fin and final["message_id"]
    tokens = "".join(d["text"] for k, d in events if k == "token")
    assert tokens.strip() and "[S1]" in tokens  # raw stream carries model labels...
    assert (
        "[1]" in final["answer"] and "[S1]" not in final["answer"]
    )  # ...the final text is validated/renumbered

    detail = (await client.get(f"{base}/conversations/{c['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["title"].startswith("How did operating margin") and detail["message_count"] == 2
    a = detail["messages"][1]
    assert a["citations"][0]["page_number"] == 1 and a["grounded"] is True and a["feedback"] is None


async def test_follow_up_uses_conversation_history(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = await convo(client, base)
    llm = Scripted(
        "Margins improved [S1].",
        plan={"standalone_question": "operating margin logistics", "search_queries": []},
    )
    app.dependency_overrides[llm_dep] = lambda: llm
    try:
        await send(client, base, c["id"], "operating margin logistics costs?")
        await send(client, base, c["id"], "and why?")
    finally:
        app.dependency_overrides.pop(llm_dep, None)
    system, msgs = llm.stream_calls[1]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "[1]" not in msgs[1]["content"]  # citation markers are stripped from history
    assert llm.plan_calls  # history triggered query rewriting


async def test_conversation_scope_limits_the_search(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    c = await convo(client, base, scope={"document_ids": [bio]})
    assert c["scope"]["document_ids"] == [bio]
    events = await send(client, base, c["id"], "How did revenue grow in Europe?")
    final = next(d for k, d in events if k == "final")
    assert final[
        "insufficient_evidence"
    ]  # revenue is only in the finance document, outside the scope
    patched = (
        await client.patch(
            f"{base}/conversations/{c['id']}", json={"scope": {"document_ids": [fin]}}
        )
    ).json()
    assert patched["scope"]["document_ids"] == [fin]
    final = next(
        d
        for k, d in await send(client, base, c["id"], "How did revenue grow in Europe?")
        if k == "final"
    )
    assert final["grounded"]


async def test_regenerate_replaces_last_answer(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = await convo(client, base)
    await send(client, base, c["id"], "How did revenue grow in Europe?")
    first = (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"][1]["id"]
    r = await client.post(f"{base}/conversations/{c['id']}/regenerate")
    assert r.status_code == 200 and "user_message" not in [k for k, _ in parse_sse(r.text)]
    msgs = (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["id"] != first
    empty = await convo(client, base)
    assert (await client.post(f"{base}/conversations/{empty['id']}/regenerate")).status_code == 409


async def test_feedback_rename_search_and_delete(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = await convo(client, base, title="Quarterly review")
    await send(client, base, c["id"], "How did revenue grow in Europe?")
    mid = (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"][1]["id"]
    assert (
        await client.put(
            f"{base}/conversations/{c['id']}/messages/{mid}/feedback",
            json={"rating": "up", "comment": "great"},
        )
    ).status_code == 204
    assert (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"][1][
        "feedback"
    ] == "up"
    await client.put(
        f"{base}/conversations/{c['id']}/messages/{mid}/feedback", json={"rating": None}
    )
    assert (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"][1][
        "feedback"
    ] is None
    assert (
        await client.patch(f"{base}/conversations/{c['id']}", json={"title": "Renamed"})
    ).json()["title"] == "Renamed"
    assert [
        x["title"]
        for x in (await client.get(f"{base}/conversations", params={"q": "renam"})).json()
    ] == ["Renamed"]
    by_content = (await client.get(f"{base}/conversations", params={"q": "revenue"})).json()
    assert [x["id"] for x in by_content] == [c["id"]]  # matches message text, not just the title
    assert (await client.get(f"{base}/conversations", params={"q": "zzzz"})).json() == []
    assert (await client.delete(f"{base}/conversations/{c['id']}")).status_code == 204
    assert await app.state.db.messages.count_documents({}) == 0
    assert (await client.get(f"{base}/conversations/{c['id']}")).status_code == 404


async def test_conversations_are_private_to_their_owner_and_workspace(client, new_client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = await convo(client, base)
    await send(client, base, c["id"], "How did revenue grow in Europe?")
    async with new_client() as other:
        await register(other, "b@example.com", "Bob")
        assert (await other.get(f"{base}/conversations")).status_code == 404  # not a member
        await client.post(f"{base}/members", json={"email": "b@example.com", "role": "admin"})
        assert (
            await other.get(f"{base}/conversations")
        ).json() == []  # even an admin sees only their own
        assert (await other.get(f"{base}/conversations/{c['id']}")).status_code == 404
        assert (await other.delete(f"{base}/conversations/{c['id']}")).status_code == 404
        assert (
            await other.post(f"{base}/conversations/{c['id']}/messages", json={"content": "hi"})
        ).status_code == 404


async def test_llm_error_arrives_as_sse_error_event_and_keeps_user_message(client, app, ai):
    ws, base, _ = await setup(client, app, FIN_BIO)
    c = await convo(client, base)

    class Down(Scripted):
        async def stream(self, *a, **k):
            raise LLMError("The AI provider timed out.", retryable=True)
            yield  # pragma: no cover

    app.dependency_overrides[llm_dep] = lambda: Down("x")
    try:
        events = await send(client, base, c["id"], "How did revenue grow in Europe?")
    finally:
        app.dependency_overrides.pop(llm_dep, None)
    err = next(d for k, d in events if k == "error")
    assert (
        err["retryable"] is True
        and "timed out" in err["message"]
        and "final" not in [k for k, _ in events]
    )
    msgs = (await client.get(f"{base}/conversations/{c['id']}")).json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]  # no fabricated assistant message


async def test_chat_requires_consent_when_external(client, app, hashing, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_provider", "anthropic")
    await register(client)
    ws = await first_workspace(client)
    base = f"/api/v1/workspaces/{ws['id']}"
    c = await convo(client, base)
    r = await client.post(f"{base}/conversations/{c['id']}/messages", json={"content": "hello"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_consent_required"


async def test_document_text_endpoint_for_the_viewer(client, app, ai):
    ws, base, (fin, bio) = await setup(client, app, FIN_BIO)
    t = (await client.get(f"{base}/documents/{fin}/text")).json()
    assert t["page_basis"] == "physical" and t["pages"][0]["number"] == 1
    assert any("operating margin" in b["text"].lower() for b in t["pages"][0]["blocks"])
    assert (await client.get(f"{base}/documents/{bio}/text")).json()["page_basis"] == "virtual"


@pytest.mark.parametrize("path", ["conversations", "conversations/abc/regenerate"])
async def test_requires_auth(client, path):
    r = await client.get(f"/api/v1/workspaces/64b7f0f0f0f0f0f0f0f0f0f0/{path}")
    assert r.status_code in (401, 405)
