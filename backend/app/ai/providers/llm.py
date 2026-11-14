"""LLM provider abstraction. Business logic depends on `LLMProvider`, never on a vendor SDK."""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
import cohere
import cohere.errors
from pydantic import BaseModel, ValidationError

from app.ai.errors import LLMError, LLMNotConfiguredError, LLMRefusalError
from app.core.config import Settings

log = logging.getLogger("documind.llm")
T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0


@dataclass
class LLMResult:
    text: str
    usage: LLMUsage
    stop_reason: str | None = None


Message = dict[str, str]  # {"role": "user"|"assistant", "content": str}


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> LLMResult: ...

    def stream(
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> AsyncIterator[str | LLMResult]:
        """Yields text deltas (str); the final item is the LLMResult."""
        ...

    async def structured(
        self,
        system: str,
        messages: list[Message],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> tuple[T, LLMUsage]: ...


def _usage(u: object, started: float) -> LLMUsage:
    return LLMUsage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _map_error(e: Exception) -> LLMError:
    """Most specific first: retryable (429/5xx/network) vs permanent (4xx)."""
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        log.error("LLM credentials rejected")
        return LLMError("The AI provider rejected the server's credentials.")
    if isinstance(e, anthropic.RateLimitError):
        return LLMError(
            "The AI provider is rate limiting requests. Try again shortly.", retryable=True
        )
    if isinstance(e, anthropic.APITimeoutError):
        return LLMError("The AI provider timed out.", retryable=True)
    if isinstance(e, anthropic.APIConnectionError):
        return LLMError("Could not reach the AI provider.", retryable=True)
    if isinstance(e, anthropic.APIStatusError):
        log.error("LLM request failed: %s %s", e.status_code, str(e)[:200])
        return LLMError("The AI provider returned an error.", retryable=e.status_code >= 500)
    return LLMError("The AI request failed.")


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        key = settings.anthropic_api_key.get_secret_value()
        self.model = settings.anthropic_model
        self._effort = settings.llm_effort
        self._max_tokens = settings.llm_max_tokens
        self._client = (
            anthropic.AsyncAnthropic(api_key=key, timeout=settings.ai_timeout_s * 3, max_retries=2)
            if key
            else None
        )

    def _require(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            raise LLMNotConfiguredError
        return self._client

    @staticmethod
    def _check_refusal(stop_reason: str | None, details: object) -> None:
        if stop_reason == "refusal":
            raise LLMRefusalError(getattr(details, "category", None))

    async def complete(
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> LLMResult:
        client = self._require()
        started = time.monotonic()
        try:
            r = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                output_config={"effort": self._effort},
            )
        except anthropic.AnthropicError as e:
            raise _map_error(e) from e
        self._check_refusal(r.stop_reason, getattr(r, "stop_details", None))
        text = "".join(b.text for b in r.content if b.type == "text")
        return LLMResult(text, _usage(r.usage, started), r.stop_reason)

    async def stream(  # type: ignore[override]
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> AsyncIterator[str | LLMResult]:
        client = self._require()
        started = time.monotonic()
        try:
            async with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                output_config={"effort": self._effort},
            ) as s:
                async for delta in s.text_stream:
                    yield delta
                final = await s.get_final_message()
        except anthropic.AnthropicError as e:
            raise _map_error(e) from e
        self._check_refusal(final.stop_reason, getattr(final, "stop_details", None))
        text = "".join(b.text for b in final.content if b.type == "text")
        yield LLMResult(text, _usage(final.usage, started), final.stop_reason)

    async def structured(
        self,
        system: str,
        messages: list[Message],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> tuple[T, LLMUsage]:
        client = self._require()
        started = time.monotonic()
        try:
            r = await client.messages.parse(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
                output_format=schema,
            )
        except anthropic.AnthropicError as e:
            raise _map_error(e) from e
        self._check_refusal(r.stop_reason, getattr(r, "stop_details", None))
        if r.parsed_output is None:
            raise LLMError("The model returned an unreadable structured response.", retryable=True)
        return r.parsed_output, _usage(r.usage, started)


# JSON-schema keywords Cohere's structured output rejects (it answered 400 on maxLength/maxItems).
# They are dropped from the schema sent to the API; Pydantic still enforces them on the result.
_COHERE_UNSUPPORTED = {
    "maxLength", "minLength", "maxItems", "minItems", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "pattern", "default", "title",
}  # fmt: skip


def cohere_schema(model: type[BaseModel]) -> dict:
    def clean(n: object) -> object:
        if isinstance(n, dict):
            out = {k: clean(v) for k, v in n.items() if k not in _COHERE_UNSUPPORTED}
            if isinstance(out.get("properties"), dict):
                # Cohere omits optional fields entirely, so every field is declared required
                # (nullable ones may still be null).
                out["required"] = list(out["properties"])
            return out
        if isinstance(n, list):
            return [clean(x) for x in n]
        return n

    return clean(model.model_json_schema())  # type: ignore[return-value]


def _cohere_error(e: Exception) -> LLMError:
    """Never falls back to another (paid) provider: limits are reported to the user as they are."""
    if isinstance(e, cohere.errors.TooManyRequestsError):
        return LLMError(
            "The Cohere trial limit was reached (40 calls per minute and 1,000 per month). "
            "Wait a minute and try again; no other provider is used.",
            retryable=True,
        )
    if isinstance(e, cohere.errors.UnauthorizedError | cohere.errors.ForbiddenError):
        log.error("Cohere credentials rejected")
        return LLMError("The AI provider rejected the server's credentials.")
    if isinstance(
        e,
        cohere.errors.ServiceUnavailableError
        | cohere.errors.InternalServerError
        | cohere.errors.GatewayTimeoutError,
    ):
        return LLMError("The AI provider is temporarily unavailable.", retryable=True)
    if isinstance(e, cohere.errors.BadRequestError):
        log.error("Cohere rejected a request: %s", str(getattr(e, "body", ""))[:300])
        return LLMError("The AI provider rejected the request.")
    if isinstance(e, TimeoutError | OSError):
        return LLMError("Could not reach the AI provider.", retryable=True)
    log.error("Cohere request failed: %s", type(e).__name__)
    return LLMError("The AI request failed.")


class CohereLLM:
    """Cohere v2 Chat API (official SDK). Works with a free Trial key."""

    name = "cohere"

    def __init__(self, settings: Settings) -> None:
        key = settings.cohere_api_key.get_secret_value()
        self.model = settings.cohere_model
        self._max_tokens = settings.llm_max_tokens
        self._client = (
            cohere.AsyncClientV2(api_key=key, timeout=settings.ai_timeout_s * 3) if key else None
        )

    def _require(self) -> "cohere.AsyncClientV2":
        if self._client is None:
            raise LLMNotConfiguredError
        return self._client

    @staticmethod
    def _usage(resp_usage: object, started: float) -> LLMUsage:
        t = getattr(resp_usage, "tokens", None)
        return LLMUsage(
            input_tokens=int(getattr(t, "input_tokens", 0) or 0),
            output_tokens=int(getattr(t, "output_tokens", 0) or 0),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _msgs(system: str, messages: list[Message]) -> list[dict]:
        return [{"role": "system", "content": system}, *messages]

    async def complete(
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> LLMResult:
        client, started = self._require(), time.monotonic()
        try:
            r = await client.chat(
                model=self.model, messages=self._msgs(system, messages),  # type: ignore[arg-type]
                max_tokens=max_tokens or self._max_tokens, temperature=0.2,
            )  # fmt: skip
        except Exception as e:
            raise _cohere_error(e) from e
        text = "".join(
            c.text for c in (r.message.content or []) if getattr(c, "type", "") == "text"
        )
        return LLMResult(text, self._usage(r.usage, started), str(r.finish_reason))

    async def stream(  # type: ignore[override]
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> AsyncIterator[str | LLMResult]:
        client, started = self._require(), time.monotonic()
        parts: list[str] = []
        finish, usage = None, None
        try:
            async for ev in client.chat_stream(
                model=self.model, messages=self._msgs(system, messages),  # type: ignore[arg-type]
                max_tokens=max_tokens or self._max_tokens, temperature=0.2,
            ):  # fmt: skip
                if ev.type == "content-delta":
                    delta = ev.delta.message.content.text
                    parts.append(delta)
                    yield delta
                elif ev.type == "message-end":
                    finish, usage = ev.delta.finish_reason, ev.delta.usage
        except Exception as e:
            raise _cohere_error(e) from e
        yield LLMResult("".join(parts), self._usage(usage, started), str(finish))

    async def structured(
        self,
        system: str,
        messages: list[Message],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> tuple[T, LLMUsage]:
        client, started = self._require(), time.monotonic()
        try:
            r = await client.chat(
                model=self.model, messages=self._msgs(system, messages),  # type: ignore[arg-type]
                response_format={"type": "json_object", "json_schema": cohere_schema(schema)},  # type: ignore[arg-type]
                max_tokens=max_tokens or self._max_tokens, temperature=0,
            )  # fmt: skip
        except Exception as e:
            raise _cohere_error(e) from e
        text = "".join(
            c.text for c in (r.message.content or []) if getattr(c, "type", "") == "text"
        )
        try:
            return schema.model_validate_json(text), self._usage(r.usage, started)
        except ValidationError as e:
            log.warning(
                "Cohere structured output failed validation for %s (finish=%s)",
                schema.__name__,
                r.finish_reason,
            )
            raise LLMError(
                "The model returned an unreadable structured response.", retryable=True
            ) from e


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings)
    if settings.llm_provider == "cohere":
        return CohereLLM(settings)
    if settings.env == "production":
        raise RuntimeError("LLM_PROVIDER=fake is not allowed in production")
    from app.ai.providers.fake import ExtractiveFakeLLM

    return ExtractiveFakeLLM()
