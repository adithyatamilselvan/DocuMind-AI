"""Retrieval-only evaluation (no LLM): does the right document show up, and how high?

Metrics per search mode: recall@1, recall@3, recall@5, MRR, mean latency (ms).
Generation quality (faithfulness, citation accuracy against a real model) is evaluated separately
in the opt-in integration suite because it needs live provider calls and costs money."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# search(question, mode) -> ranked list of document titles (best first, may repeat)
SearchFn = Callable[[str, str], Awaitable[list[str]]]


@dataclass
class ModeResult:
    mode: str
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    mean_latency_ms: float
    misses: list[str]


def _dedupe(ranked: list[str]) -> list[str]:
    return list(dict.fromkeys(ranked))


async def evaluate(search: SearchFn, questions: list[tuple[str, str]], mode: str) -> ModeResult:
    hits = {1: 0, 3: 0, 5: 0}
    rr = 0.0
    latency = 0.0
    misses: list[str] = []
    for question, expected in questions:
        t0 = time.monotonic()
        ranked = _dedupe(await search(question, mode))
        latency += (time.monotonic() - t0) * 1000
        for k in hits:
            hits[k] += expected in ranked[:k]
        if expected in ranked:
            rr += 1 / (ranked.index(expected) + 1)
        else:
            misses.append(question)
    n = len(questions)
    return ModeResult(mode, hits[1] / n, hits[3] / n, hits[5] / n, rr / n, latency / n, misses)
