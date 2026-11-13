"""LLM provider abstraction. Business logic depends on `LLMProvider`, never on a vendor SDK."""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

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


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings)
    if settings.env == "production":
        raise RuntimeError("LLM_PROVIDER=fake is not allowed in production")
    from app.ai.providers.fake import ExtractiveFakeLLM

    return ExtractiveFakeLLM()
