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
        if schema.__name__ in {"DocumentInsights", "SectionNotes"}:
            prompt = messages[-1]["content"]
            data = (
                fake_document_insights(prompt)
                if schema.__name__ == "DocumentInsights"
                else fake_section_notes(prompt)
            )
            return schema.model_validate(data), LLMUsage(
                input_tokens=len(prompt) // 4, output_tokens=200
            )
        if schema.__name__ in {"PaperAnalysis", "Synthesis"}:
            prompt = messages[-1]["content"]
            data = (
                fake_paper_analysis(prompt)
                if schema.__name__ == "PaperAnalysis"
                else fake_synthesis(prompt)
            )
            return schema.model_validate(data), LLMUsage(
                input_tokens=len(prompt) // 4, output_tokens=300
            )
        if schema.__name__ in {"ComparisonResult", "VersionSummary"}:
            prompt = messages[-1]["content"]
            data = (
                fake_comparison(prompt)
                if schema.__name__ == "ComparisonResult"
                else fake_version_summary(prompt)
            )
            return schema.model_validate(data), LLMUsage(
                input_tokens=len(prompt) // 4, output_tokens=200
            )
        raise LLMError(f"The fake LLM does not support structured output for {schema.__name__}")


# ---- deterministic insights for LLM_PROVIDER=fake (tests / offline demos) ----

_PAGE = re.compile(r"\[(?:Page|Section) (\d+)\]\n(.*?)(?=\n\n\[(?:Page|Section) \d+\]\n|\Z)", re.S)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_BIG = re.compile(r"[A-Za-z]{5,}")


def _fake_pages(prompt: str) -> list[tuple[int, str]]:
    body = html.unescape(prompt.split(">", 1)[1] if "<document" in prompt else prompt)
    return [(int(n), t.strip()) for n, t in _PAGE.findall(body)]


def fake_section_notes(prompt: str) -> dict:
    pages = _fake_pages(prompt)
    points = []
    for n, text in pages[:10]:
        sent = next((s for s in _SENT.split(text) if len(s) >= 30), None)
        if sent:
            points.append({"text": sent[:200], "page": n, "quote": sent[:200]})
    return {
        "summary": " ".join(p["text"] for p in points[:3])[:1400] or "No content.",
        "points": points,
    }


def fake_document_insights(prompt: str) -> dict:
    pages = _fake_pages(prompt)
    sentences = [(n, s.strip()) for n, t in pages for s in _SENT.split(t) if len(s.strip()) >= 30]
    words: dict[str, int] = {}
    for _, t in pages:
        for w in _BIG.findall(t.lower()):
            words[w] = words.get(w, 0) + 1
    top = [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))][:8]

    def finding(n: int, s: str) -> dict:
        return {"text": s[:300], "page": n, "quote": s[:250]}

    years = []
    for n, t in pages:
        for y in dict.fromkeys(_YEAR.findall(t)):
            years.append({"date": y, "description": f"Year {y} is mentioned", "page": n})
    return {
        "summary": " ".join(s for _, s in sentences[:3])[:1400] or "No content.",
        "executive_summary": " ".join(s for _, s in sentences[:1])[:600] or "No content.",
        "key_findings": [finding(n, s) for n, s in sentences[:3]],
        "key_facts": [finding(n, s) for n, s in sentences[3:5]],
        "topics": top[:5],
        "keywords": top,
        "classification": {"document_type": "document", "category": "General", "confidence": "low"},
        "entities": {"people": [], "organizations": [], "locations": []},
        "important_dates": years[:5],
        "main_arguments": [],
        "conclusions": [],
        "limitations": [],
        "action_items": [],
        "suggested_questions": [f"What does the document say about {w}?" for w in top[:3]],
    }


# ---- deterministic research analysis / synthesis for LLM_PROVIDER=fake ----


def _pick(sentences: list[tuple[int, str]], *words: str) -> list[dict]:
    out = []
    for n, s in sentences:
        if any(w in s.lower() for w in words):
            out.append({"text": s[:300], "page": n, "quote": s[:250]})
    return out[:4]


def fake_paper_analysis(prompt: str) -> dict:
    pages = _fake_pages(prompt)
    sentences = [(n, s.strip()) for n, t in pages for s in _SENT.split(t) if len(s.strip()) >= 30]
    text = " ".join(s for _, s in sentences).lower()
    method = next(
        (
            c
            for c, w in [
                ("survey", "survey"),
                ("experimental", "experiment"),
                ("simulation", "simulat"),
                ("review", "review"),
                ("qualitative", "interview"),
            ]
            if w in text
        ),
        "other",
    )
    size = re.search(r"\b(?:n\s*=\s*\d+|\d+\s+(?:participants|patients|samples|respondents))", text)
    size_sentence = next(
        ((n, s) for n, s in sentences if size and size.group(0) in s.lower()), None
    )
    limitations = _pick(sentences, "limitation", "limited")
    future = _pick(sentences, "future")
    obj = _pick(sentences, "aim", "objective", "we investigate", "purpose") or [
        {"text": s[:300], "page": n, "quote": s[:250]} for n, s in sentences[:1]
    ]
    return {
        "is_research_paper": bool(sentences),
        "objective": obj[0] if obj else None,
        "research_questions": _pick(sentences, "research question"),
        "hypotheses": _pick(sentences, "hypothes"),
        "methodology": {
            "category": method,
            "description": f"Detected from the text: {method}.",
            "evidence": _pick(sentences, method[:5])[:1],
        },
        "datasets": _pick(sentences, "dataset", "data set", "corpus"),
        "sample_size": {
            "text": size.group(0),
            "page": size_sentence[0],
            "quote": size_sentence[1][:250],
        }
        if size_sentence
        else None,
        "results": _pick(sentences, "result", "found", "show", "increase", "decrease", "percent"),
        "conclusions": _pick(sentences, "conclu"),
        "limitations": limitations,
        "future_work": future,
        "potential_gaps": [
            {
                "text": f"Open question implied by: {x['text'][:120]}",
                "rationale": "Stated as a limitation in the document.",
                "evidence": [x],
            }
            for x in limitations[:2]
        ],
    }


def fake_synthesis(prompt: str) -> dict:
    import json as _json

    body = html.unescape(prompt.split(">", 1)[1])
    papers = [_json.loads(line) for line in body.splitlines() if line.startswith('{"paper"')]
    items, rows, gaps = [], [], []
    for p in papers:
        a = p["analysis"]
        res = (a.get("results") or [None])[0]
        if res:
            items.append(
                {
                    "text": res["text"],
                    "paper": p["paper"],
                    "page": res.get("page"),
                    "quote": res.get("quote"),
                }
            )
        rows.append(
            {
                "paper": p["paper"],
                "methodology": a["methodology"]["category"],
                "datasets": "; ".join(d["text"] for d in a.get("datasets", []))[:200],
                "sample_size": (a.get("sample_size") or {}).get("text", ""),
                "key_result": (res or {}).get("text", "")[:300],
            }
        )
        gaps += [
            {"text": g["text"], "rationale": g["rationale"], "papers": [p["paper"]]}
            for g in a.get("potential_gaps", [])[:1]
        ]
    return {
        "overview": "Synthesis of: " + "; ".join(p["title"] for p in papers),
        "themes": [
            {
                "title": "Reported results",
                "summary": "Key results reported in each paper.",
                "items": items,
            }
        ]
        if items
        else [],
        "comparison_table": rows,
        "contradictions": [],
        "trends": [],
        "research_gaps": gaps,
    }


# ---- deterministic comparison for LLM_PROVIDER=fake ----

_PASSAGE = re.compile(r'<passage label="([^"]+)" document="(\d+)"[^>]*>\n(.*?)\n</passage>', re.S)
_ASPECT = re.compile(r'<aspect name="([^"]+)">(.*?)</aspect>', re.S)


def fake_comparison(prompt: str) -> dict:
    aspects = []
    for name, body in _ASPECT.findall(prompt):
        first: dict[str, tuple[str, str]] = {}
        for label, doc, text in _PASSAGE.findall(body):
            sent = next((s for s in _SENT.split(html.unescape(text)) if len(s) > 25), None)
            if sent and doc not in first:
                first[doc] = (label, sent.strip())
        docs = sorted(first)
        diffs = [
            {"text": f"Document {d} says: {first[d][1][:200]}", "sources": [first[d][0]]}
            for d in docs
        ]
        sims = []
        if len(docs) >= 2:
            common = _terms(first[docs[0]][1]) & _terms(first[docs[1]][1])
            if len(common) >= 3:
                sims.append(
                    {
                        "text": "Both discuss: " + ", ".join(sorted(common)[:4]),
                        "sources": [first[docs[0]][0], first[docs[1]][0]],
                    }
                )
        aspects.append(
            {
                "aspect": name,
                "similarities": sims,
                "differences": diffs,
                "conflicts": [],
                "missing_information": [],
            }
        )
    return {"summary": f"Compared {len(aspects)} aspects.", "aspects": aspects}


def fake_version_summary(prompt: str) -> dict:
    body = html.unescape(prompt)
    lines = [ln for ln in body.splitlines() if ln.startswith(("ADDED", "REMOVED", "CHANGED"))]
    return {
        "summary": f"{len(lines)} change(s) between the versions.",
        "notable_changes": [ln[:150] for ln in lines[:5]],
    }
