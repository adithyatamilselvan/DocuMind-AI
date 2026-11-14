# Architecture

```
Browser ──► Next.js (BFF rewrite /api) ──► FastAPI ──► MongoDB (data, Atlas Vector/Search)
                                              │──► Object storage (S3/MinIO or local dev dir)
                                              │──► Redis ◄── Celery workers (ingestion, insights, research, comparison, reports)
                                              └──► AI providers (Anthropic LLM, OpenAI/local embeddings) behind interfaces
```

## Frontend ↔ backend
Same-origin: Next rewrites `/api/*` to FastAPI, so session cookies are first-party and CORS is unnecessary. The backend is the only
authorization boundary (Next's `proxy.ts` only does optimistic redirects). Types come from the OpenAPI schema (`npm run gen:api`).
Uploads use XHR for progress; chat uses `fetch` + a hand-written SSE parser. `/api` is excluded from the Next proxy matcher so large uploads
are not buffered (Next would truncate bodies at 10 MB).

## Modules (`backend/app/modules`)
`auth`, `users` (+privacy), `workspaces` (RBAC, purge), `documents` (library, upload, validation, malware), `collections`, `knowledge_bases`,
`ingestion` (orchestrator, queues, stages), `extraction` (PDF/DOCX/TXT/OCR), `chunking`, `vector_search` (Atlas + local), `retrieval`
(scope, RRF, rerank), `rag` (pipeline, citations), `chat` (conversations, SSE), `insights`, `research`, `comparison`, `reports`,
`analytics` (overview, audit, usage), `audit`, `usage`.

## Ingestion pipeline
Upload → validate (extension + **content sniffing**, zip-bomb limits) → stream to temp with size cap + SHA-256 → duplicate check →
private object store → `documents`/`document_versions` → job queued. Worker stages, each checkpointed on the job (resumable/idempotent):

1. `extract` (EXTRACTING; OCR_PROCESSING if scanned pages): PyMuPDF text layer in reading order, font-based headings, tables, header/footer
   removal; Tesseract for pages with no text layer; DOCX/TXT readers. Output stored as `extracted.json` beside the original.
2. `chunk` (CHUNKING): heading-aware, never crosses a page, tables as own chunks, sentence-aligned overlap.
3. `embed` (EMBEDDING): batches; only missing chunks on resume; consent re-checked; usage recorded.
4. `index` (INDEXING): verifies the search index is ready, then atomically makes the version's chunks searchable and removes older versions' chunks.
5. `COMPLETED` is set only after all stages succeed; an `insights` job is then queued separately (it never blocks completion).

Status transitions are validated in one table (`documents/states.py`). Transient errors retry with backoff (`RetryLater`); permanent errors set
`FAILED` with a user-safe message. `recover_stuck_jobs` re-enqueues jobs from a dead process.

## RAG and citation integrity
`question → query understanding (standalone rewrite + up to 3 queries) → server-side scope (workspace ∩ filters, never client-trusted) →
hybrid retrieval (vector + keyword per query → RRF → threshold → near-duplicate removal → rerank) → context selection (token budget,
document diversity) → generation (sources escaped, injection-hardened prompt) → citation validation → response`.

- The model sees opaque ids (S1..Sn). Document, page and passage in every citation come from the stored chunk, never from model text.
- Unknown ids are removed; quotes must appear verbatim in a retrieved source or lose their quotation marks (warning shown);
  an answer with no valid citation is withheld; no retrieved evidence means **no LLM call**.
- Insights, research, comparison and reports reuse the same principle: every quote/page is checked against extracted text and dropped if unverifiable.
- DOCX/TXT have no real pages: their "pages" are virtual sections and are flagged approximate in the UI and API (`page_is_exact`).

## Async AI jobs
Insights, research, comparison and report jobs share the `processing_jobs` collection and one handler registry (`ingestion/handlers.py`).
`JOB_BACKEND=celery` (Redis workers) in production; `inline` (asyncio in the API process) for development without Redis.

## Provider abstraction
`LLMProvider`, `EmbeddingProvider`, `Reranker`, `OCREngine`, `ObjectStore`, `VectorStore`, `EmailSender`, `Scanner`: business logic imports interfaces only.
Test-only implementations (`fake` LLM, `hashing` embedder, local vector scan) are refused when `APP_ENV=production`.

## Decisions
See `docs/adr/`. Notable: PyMongo Async + one async pipeline (Celery tasks call `asyncio.run`), server-side opaque sessions with HMAC CSRF,
hosted-first embeddings, Next 16 `proxy.ts`, Base UI components (`LinkButton` instead of `Button render={<Link/>}`).
