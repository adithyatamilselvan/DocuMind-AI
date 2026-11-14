"""Build structured report content from stored, already-verified analyses. No new LLM calls:
every statement and reference comes from an insights / research / comparison record."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Refs:
    items: list[dict[str, Any]] = field(default_factory=list)
    _index: dict[tuple, int] = field(default_factory=dict)

    def add(
        self, document_id: str | None, title: str, page: int | None, quote: str | None
    ) -> int | None:
        if not title or (page is None and not quote):
            return None
        key = (document_id, page, quote)
        if key not in self._index:
            self.items.append(
                {
                    "n": len(self.items) + 1,
                    "document_id": document_id,
                    "document_title": title,
                    "page": page,
                    "quote": quote,
                }
            )
            self._index[key] = len(self.items)
        return self._index[key]


def bullets(
    findings: list[dict[str, Any]], refs: Refs, doc_id: str | None, title: str
) -> list[dict[str, Any]]:
    out = []
    for f in findings or []:
        n = refs.add(doc_id, title, f.get("page"), f.get("quote"))
        out.append({"text": f["text"], "refs": [n] if n else []})
    return out


def section(title: str, *, paragraphs: list[str] | None = None, bullet_list: list[dict[str, Any]] | None = None,
            table: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "title": title,
        "paragraphs": paragraphs or [],
        "bullets": bullet_list or [],
        "table": table,
    }


def keep(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sections if s["paragraphs"] or s["bullets"] or s["table"]]


def from_insights(doc: dict[str, Any], rec: dict[str, Any], refs: Refs) -> list[dict[str, Any]]:
    p, did, title = rec["payload"], str(doc["_id"]), doc["title"]
    cls = p.get("classification", {})
    return keep([
        section("Executive summary", paragraphs=[p["executive_summary"]]),
        section("Summary", paragraphs=[p["summary"]]),
        section("Classification", paragraphs=[f"{cls.get('document_type', '')} · {cls.get('category', '')}"]),
        section("Key findings", bullet_list=bullets(p["key_findings"], refs, did, title)),
        section("Important facts", bullet_list=bullets(p["key_facts"], refs, did, title)),
        section("Main arguments", bullet_list=bullets(p["main_arguments"], refs, did, title)),
        section("Conclusions", bullet_list=bullets(p["conclusions"], refs, did, title)),
        section("Limitations", bullet_list=bullets(p["limitations"], refs, did, title)),
        section("Action items", bullet_list=[{"text": a, "refs": []} for a in p["action_items"]]),
        section("Topics", paragraphs=[", ".join(p["topics"])] if p["topics"] else None),
    ])  # fmt: skip


def from_paper(doc: dict[str, Any], rec: dict[str, Any], refs: Refs) -> list[dict[str, Any]]:
    r, did, title = rec["result"], str(doc["_id"]), doc["title"]

    def one(f: dict[str, Any] | None) -> list[dict[str, Any]]:
        return bullets([f], refs, did, title) if f else []

    m = r["methodology"]
    return keep([
        section("Objective", bullet_list=one(r.get("objective"))),
        section("Research questions", bullet_list=bullets(r["research_questions"], refs, did, title)),
        section("Hypotheses", bullet_list=bullets(r["hypotheses"], refs, did, title)),
        section("Methodology", paragraphs=[f"Category: {m['category']}. {m['description']}".strip()], bullet_list=bullets(m["evidence"], refs, did, title)),
        section("Datasets", bullet_list=bullets(r["datasets"], refs, did, title)),
        section("Sample size", bullet_list=one(r.get("sample_size"))),
        section("Results", bullet_list=bullets(r["results"], refs, did, title)),
        section("Conclusions", bullet_list=bullets(r["conclusions"], refs, did, title)),
        section("Limitations", bullet_list=bullets(r["limitations"], refs, did, title)),
        section("Future work", bullet_list=bullets(r["future_work"], refs, did, title)),
        section(
            "Potential research gaps (AI-identified, not stated by the authors)",
            bullet_list=[
                {"text": f"{g['text']} Rationale: {g['rationale']}", "refs": [n for n in (refs.add(did, title, e.get("page"), e.get("quote")) for e in g["evidence"]) if n]}
                for g in r["potential_gaps"]
            ],
        ),
    ])  # fmt: skip


def from_synthesis(rec: dict[str, Any], refs: Refs) -> list[dict[str, Any]]:
    r = rec["result"]
    papers = {p["index"]: p for p in r["papers"]}

    def ref(item: dict[str, Any]) -> list[int]:
        p = papers.get(item["paper"])
        n = (
            refs.add(p["document_id"], p["title"], item.get("page"), item.get("quote"))
            if p
            else None
        )
        return [n] if n else []

    sections = [section("Overview", paragraphs=[r["overview"]])]
    for t in r["themes"]:
        sections.append(
            section(
                f"Theme: {t['title']}",
                paragraphs=[t["summary"]],
                bullet_list=[
                    {"text": f"[{papers[i['paper']]['title']}] {i['text']}", "refs": ref(i)}
                    for i in t["items"]
                    if i["paper"] in papers
                ],
            )
        )
    if r["comparison_table"]:
        sections.append(
            section(
                "Comparison of papers",
                table={
                    "columns": ["Paper", "Methodology", "Datasets", "Sample size", "Key result"],
                    "rows": [
                        [
                            papers[x["paper"]]["title"],
                            x["methodology"],
                            x["datasets"],
                            x["sample_size"],
                            x["key_result"],
                        ]
                        for x in r["comparison_table"]
                        if x["paper"] in papers
                    ],
                },
            )
        )
    if r["contradictions"]:
        sections.append(
            section(
                "Contradictory findings",
                bullet_list=[
                    {
                        "text": f"{c['topic']}: {c['explanation']}",
                        "refs": [n for p in c["positions"] for n in ref(p)],
                    }
                    for c in r["contradictions"]
                ],
            )
        )
    sections.append(
        section("Trends", bullet_list=[{"text": t["text"], "refs": ref(t)} for t in r["trends"]])
    )
    sections.append(
        section(
            "Potential research gaps (AI-identified suggestions, not established facts)",
            bullet_list=[
                {"text": f"{g['text']} Rationale: {g['rationale']}", "refs": []}
                for g in r["research_gaps"]
            ],
        )
    )
    return keep(sections)


def from_comparison(rec: dict[str, Any], refs: Refs) -> list[dict[str, Any]]:
    r = rec["result"]
    if rec["kind"] == "versions":
        st = r["stats"]
        sections = [
            section(
                "Summary",
                paragraphs=[
                    r["summary"] or r.get("summary_note") or "No AI summary available.",
                    f"{st['added']} added, {st['removed']} removed, {st['changed']} changed paragraph(s).",
                ],
            )
        ]
        sections.append(
            section(
                "Notable changes",
                bullet_list=[{"text": c, "refs": []} for c in r.get("notable_changes", [])],
            )
        )
        sections.append(
            section(
                "Changed passages",
                bullet_list=[
                    {"text": f"Before: {c['before'][:300]}  After: {c['after'][:300]}", "refs": []}
                    for c in r["changed"][:30]
                ],
            )
        )
        sections.append(
            section(
                "Added passages",
                bullet_list=[{"text": a["text"][:400], "refs": []} for a in r["added"][:30]],
            )
        )
        sections.append(
            section(
                "Removed passages",
                bullet_list=[{"text": a["text"][:400], "refs": []} for a in r["removed"][:30]],
            )
        )
        return keep(sections)
    srcs = r["sources"]

    def b(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for p in points:
            ns = [
                n
                for s in p["sources"]
                if s in srcs
                for n in [
                    refs.add(
                        srcs[s]["document_id"],
                        srcs[s]["document_title"],
                        srcs[s]["page_number"],
                        srcs[s]["snippet"][:200],
                    )
                ]
                if n
            ]
            out.append({"text": p["text"], "refs": ns})
        return out

    sections = [
        section(
            "Documents compared",
            bullet_list=[{"text": d["title"], "refs": []} for d in r["documents"]],
        ),
        section("Summary", paragraphs=[r["summary"]]),
    ]
    for a in r["aspects"]:
        sections += [
            section(f"{a['aspect']}: similarities", bullet_list=b(a["similarities"])),
            section(f"{a['aspect']}: differences", bullet_list=b(a["differences"])),
            section(f"{a['aspect']}: conflicting statements", bullet_list=b(a["conflicts"])),
            section(f"{a['aspect']}: missing information", bullet_list=b(a["missing_information"])),
        ]
    return keep(sections)


def from_multi_insights(
    docs: list[tuple[dict[str, Any], dict[str, Any]]], refs: Refs, executive_only: bool
) -> list[dict[str, Any]]:
    sections = [
        section(
            "Executive overview",
            bullet_list=[
                {"text": f"{d['title']}: {r['payload']['executive_summary']}", "refs": []}
                for d, r in docs
            ],
        )
    ]
    if not executive_only:
        sections.append(
            section(
                "Documents at a glance",
                table={
                    "columns": ["Document", "Type", "Category", "Topics"],
                    "rows": [
                        [
                            d["title"],
                            r["payload"]["classification"].get("document_type", ""),
                            r["payload"]["classification"].get("category", ""),
                            ", ".join(r["payload"]["topics"][:5]),
                        ]
                        for d, r in docs
                    ],
                },
            )
        )
    for d, r in docs:
        sections.append(
            section(
                f"Key findings: {d['title']}",
                bullet_list=bullets(r["payload"]["key_findings"], refs, str(d["_id"]), d["title"]),
            )
        )
        if not executive_only:
            sections.append(
                section(
                    f"Conclusions: {d['title']}",
                    bullet_list=bullets(
                        r["payload"]["conclusions"], refs, str(d["_id"]), d["title"]
                    ),
                )
            )
    return keep(sections)
