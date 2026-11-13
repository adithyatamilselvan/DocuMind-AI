"""Deterministic extractive stand-in for an LLM. FOR TESTS AND OFFLINE DEVELOPMENT ONLY
(LLM_PROVIDER=fake; blocked in production). It does not understand language: it quotes the
sentence from the provided sources that best overlaps the question, with a citation."""

import html
import re
from collections.abc import AsyncIterator
from typing import TypeVar

from pydantic import BaseModel

from app.ai.errors import LLMError
from app.ai.providers.llm import LLMResult, LLMUsage, Message

T = TypeVar("T", bound=BaseModel)
_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.S)
_SENT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\w+")
_STOP = {
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "and",
    "is",
    "are",
    "what",
    "how",
    "did",
    "do",
    "for",
    "on",
}


def _terms(t: str) -> set[str]:
    return {w for w in _WORD.findall(t.lower()) if w not in _STOP and len(w) > 2}


class ExtractiveFakeLLM:
    name = "fake"
    model = "fake-extractive"

    def _answer(self, messages: list[Message]) -> str:
        last = messages[-1]["content"]
        question = last.rsplit("Question:", 1)[-1].strip()
        q = _terms(question)
        best: tuple[int, str, str] | None = None
        for label, body in _SOURCE.findall(last):
            for sent in _SENT.split(html.unescape(body)):
                score = len(q & _terms(sent))
                if score and (best is None or score > best[0]) and len(sent) >= 25:
                    best = (score, label, sent.strip())
        if best is None:
            return "NO_EVIDENCE: none of the provided sources mention this."
        _, label, sent = best
        return f'The documents state: "{sent}" [{label}]'

    async def complete(
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> LLMResult:
        text = self._answer(messages)
        return LLMResult(
            text,
            LLMUsage(input_tokens=len(messages[-1]["content"]) // 4, output_tokens=len(text) // 4),
            "end_turn",
        )

    async def stream(  # type: ignore[override]
        self, system: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> AsyncIterator[str | LLMResult]:
        r = await self.complete(system, messages)
        words = r.text.split(" ")
        for i in range(0, len(words), 3):
            yield " ".join(words[i : i + 3]) + (" " if i + 3 < len(words) else "")
        yield r

    async def structured(
        self,
        system: str,
        messages: list[Message],
        schema: type[T],
        *,
        max_tokens: int | None = None,
    ) -> tuple[T, LLMUsage]:
        if schema.__name__ == "QueryPlan":
            question = messages[-1]["content"].rsplit("Latest question:", 1)[-1].strip()
            return schema.model_validate(
                {"standalone_question": question, "search_queries": []}
            ), LLMUsage()
        raise LLMError(f"The fake LLM does not support structured output for {schema.__name__}")
