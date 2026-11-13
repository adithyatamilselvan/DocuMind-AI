from collections import Counter

from app.modules.retrieval.service import RetrievedChunk


def select_context(
    ranked: list[RetrievedChunk], *, top_k: int, token_budget: int
) -> dict[str, RetrievedChunk]:
    """Pick the chunks the model will see, within `top_k` and a token budget.

    - Diversity first: when several documents match, no single document takes more than half the
      slots in the first pass, so a multi-document question sees evidence from each. Slots still
      free afterwards are filled in rank order (the cap is a preference, not a limit).
    - Selected chunks are presented in reading order (document, page, position) and labelled S1..Sn.
    """
    docs_in_ranking = len({c.document_id for c in ranked})
    per_doc_cap = top_k if docs_in_ranking <= 1 else max(2, (top_k + 1) // 2)
    taken: list[RetrievedChunk] = []
    skipped: list[RetrievedChunk] = []
    per_doc: Counter = Counter()
    used = 0

    def cost(c: RetrievedChunk) -> int:
        return max(c.token_count, len(c.content) // 4)

    for c in ranked:
        if len(taken) >= top_k:
            break
        if per_doc[c.document_id] >= per_doc_cap:
            skipped.append(c)
            continue
        if used + cost(c) > token_budget and taken:
            continue
        taken.append(c)
        per_doc[c.document_id] += 1
        used += cost(c)
    for c in skipped:
        if len(taken) >= top_k:
            break
        if used + cost(c) <= token_budget:
            taken.append(c)
            used += cost(c)
    taken.sort(
        key=lambda c: (
            c.document_title.lower(),
            str(c.document_id),
            c.page_number or 0,
            c.chunk_index,
        )
    )
    return {f"S{i}": c for i, c in enumerate(taken, start=1)}
