import json
from types import SimpleNamespace as NS

import cohere.errors as ce
import pytest
from pydantic import SecretStr

from app.ai.errors import LLMError, LLMNotConfiguredError
from app.ai.providers.llm import CohereLLM, build_llm, cohere_schema
from app.core.config import get_settings
from app.modules.insights.schemas import DocumentInsights
from app.modules.rag.schemas import QueryPlan

from .conftest import enable_ai, first_workspace, register

KEY = "co-test-key-should-never-leak"


def settings(**over):
    return get_settings().model_copy(
        update={"llm_provider": "cohere", "cohere_api_key": SecretStr(KEY), **over}
    )


class FakeClient:
    """Stands in for cohere.AsyncClientV2; records every call."""

    def __init__(self, reply=None, stream_events=None, error=None):
        self.calls, self.reply, self.stream_events, self.error = (
            [],
            reply,
            stream_events or [],
            error,
        )

    async def chat(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        usage = NS(tokens=NS(input_tokens=120, output_tokens=15))
        return NS(
            message=NS(content=[NS(type="text", text=self.reply)]),
            usage=usage,
            finish_reason="COMPLETE",
        )

    async def chat_stream(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        for ev in self.stream_events:
            yield ev


def llm_with(client, **over):
    llm = CohereLLM(settings(**over))
    llm._client = client
    return llm


def delta(text):
    return NS(type="content-delta", delta=NS(message=NS(content=NS(text=text))))


END = NS(
    type="message-end",
    delta=NS(finish_reason="COMPLETE", usage=NS(tokens=NS(input_tokens=200, output_tokens=30))),
)


def test_settings_and_factory_select_cohere_without_any_anthropic_key():
    s = settings()
    assert s.anthropic_api_key.get_secret_value() == "" and s.llm_configured and s.ai_external
    assert isinstance(build_llm(s), CohereLLM) and build_llm(s).model == "command-a-03-2025"
    assert not settings(cohere_api_key=SecretStr("")).llm_configured
    assert KEY not in repr(s)  # secret is never rendered


async def test_complete_request_shape_and_usage():
    c = FakeClient(reply="Paris")
    r = await llm_with(c).complete("SYS", [{"role": "user", "content": "q"}])
    kw = c.calls[0]
    assert kw["model"] == "command-a-03-2025" and kw["messages"][0] == {
        "role": "system",
        "content": "SYS",
    }
    assert kw["messages"][1] == {"role": "user", "content": "q"} and kw["temperature"] == 0.2
    assert KEY not in json.dumps(kw, default=str)  # the key is only configured on the client
    assert (r.text, r.usage.input_tokens, r.usage.output_tokens, r.stop_reason) == (
        "Paris",
        120,
        15,
        "COMPLETE",
    )


async def test_streaming_yields_deltas_then_the_final_result():
    c = FakeClient(stream_events=[NS(type="message-start"), delta("Hello "), delta("world"), END])
    items = [i async for i in llm_with(c).stream("S", [{"role": "user", "content": "q"}])]
    assert items[:2] == ["Hello ", "world"] and items[2].text == "Hello world"
    assert (items[2].usage.input_tokens, items[2].usage.output_tokens) == (200, 30)


def test_schema_sent_to_cohere_has_no_unsupported_constraints_but_pydantic_still_enforces_them():
    for model in (QueryPlan, DocumentInsights):
        text = json.dumps(cohere_schema(model))
        assert not any(k in text for k in ("maxLength", "maxItems", "minItems", "minLength"))
    sch = cohere_schema(DocumentInsights)
    assert set(sch["required"]) == set(
        sch["properties"]
    )  # optional fields would otherwise be omitted by Cohere
    with pytest.raises(Exception):
        QueryPlan(standalone_question="x" * 5000)  # limits are still validated locally


async def test_structured_output_parses_and_validates():
    plan = {
        "standalone_question": "How did margin change?",
        "search_queries": ["margin"],
        "intent": "factual",
    }
    c = FakeClient(reply=json.dumps(plan))
    out, usage = await llm_with(c).structured("S", [{"role": "user", "content": "q"}], QueryPlan)
    assert out.standalone_question == "How did margin change?" and usage.input_tokens == 120
    rf = c.calls[0]["response_format"]
    assert (
        rf["type"] == "json_object"
        and "maxLength" not in json.dumps(rf["json_schema"])
        and c.calls[0]["temperature"] == 0
    )
    bad = llm_with(FakeClient(reply='{"standalone_question": 5}'))
    with pytest.raises(LLMError) as e:
        await bad.structured("S", [{"role": "user", "content": "q"}], QueryPlan)
    assert e.value.retryable  # unreadable output is retried, never shown raw


@pytest.mark.parametrize(
    ("exc", "retryable", "needle"),
    [
        (ce.TooManyRequestsError(body={"message": "trial key limit"}), True, "trial limit"),
        (ce.ServiceUnavailableError(body={}), True, "unavailable"),
        (ce.UnauthorizedError(body={"message": KEY}), False, "credentials"),
        (ce.BadRequestError(body={"message": "bad"}), False, "rejected"),
    ],
)
async def test_provider_errors_map_to_safe_user_messages(exc, retryable, needle):
    llm = llm_with(FakeClient(error=exc))
    with pytest.raises(LLMError) as e:
        await llm.complete("S", [{"role": "user", "content": "q"}])
    assert e.value.retryable is retryable and needle in e.value.message
    assert KEY not in e.value.message
    assert (
        "no other provider is used" in (await _msg(llm)).lower()
        if needle == "trial limit"
        else True
    )


async def _msg(llm):
    try:
        await llm.complete("S", [{"role": "user", "content": "q"}])
    except LLMError as e:
        return e.message


async def test_stream_errors_and_missing_key():
    with pytest.raises(LLMError) as e:
        async for _ in llm_with(FakeClient(error=ce.TooManyRequestsError(body={}))).stream(
            "S", [{"role": "user", "content": "q"}]
        ):
            pass
    assert e.value.retryable
    with pytest.raises(LLMNotConfiguredError):
        await CohereLLM(settings(cohere_api_key=SecretStr(""))).complete(
            "S", [{"role": "user", "content": "q"}]
        )


# ---------- real Cohere Trial call + real local embeddings (opt-in: pytest -m integration) ----------


@pytest.mark.integration
async def test_live_cohere_full_workflow_with_local_embeddings(client, app, monkeypatch):
    """Needs COHERE_API_KEY in .env and the local embedding model. Uses ~2 Trial calls."""
    import re

    from .helpers import make_pdf
    from .test_indexing import FINANCE, upload

    key = (
        re.search(r"^COHERE_API_KEY=(.*)$", open("../.env", encoding="utf-8").read(), re.M)
        .group(1)
        .strip()
    )
    s = get_settings()
    for k, v in {
        "llm_provider": "cohere",
        "cohere_api_key": SecretStr(key),
        "embedding_provider": "local",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "insights_enabled": False,
        "rag_multi_query": False,  # conserve Trial quota
    }.items():
        monkeypatch.setattr(s, k, v)
    await register(client)
    ws = await first_workspace(client)
    await enable_ai(client, ws["id"])
    base = f"/api/v1/workspaces/{ws['id']}"
    pdf = make_pdf(
        [
            {"heading": "Cell Biology", "body": "Mitochondria generate cellular energy. " * 6},
            {"heading": "Financial Results", "body": FINANCE},
        ]
    )
    doc_id = await upload(client, base, "report.pdf", pdf)
    await app.state.queue.drain()
    assert (await client.get(f"{base}/documents/{doc_id}")).json()["status"] == "COMPLETED"
    r = await client.post(
        f"{base}/ask", json={"question": "How did operating margin and logistics costs develop?"}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    print(
        "\nANSWER:",
        d["answer"][:400],
        "\nCITATIONS:",
        [(c["document_title"], c["page_number"]) for c in d["citations"]],
        "\nWARNINGS:",
        d["warnings"],
    )
    assert d["grounded"] and d["citations"], d
    assert d["citations"][0]["document_title"] == "report" and d["citations"][0]["page_number"] == 2
    assert "logistics" in d["citations"][0]["snippet"].lower()
