# ADR-001: Core architecture decisions

Status: accepted (Phase 0)

1. **Modular monolith**: FastAPI backend with per-module `router/service/repository/schemas`.
2. **PyMongo Async** (`AsyncMongoClient`) for the API. Celery workers are synchronous and use the sync client.
3. **Cookie sessions**: opaque server-side session IDs (hashed in Mongo), HttpOnly cookie, CSRF double-submit.
4. **Same-origin API**: Next.js rewrites `/api/*` to FastAPI, so no CORS in normal use.
5. **Provider interfaces**: `LLMProvider`, `EmbeddingProvider`, `Reranker`, `OCREngine`, `ObjectStore`, `EmailSender`.
6. **Hybrid search**: vector + keyword queries merged with Reciprocal Rank Fusion in application code.
7. **Citations are structural**: the LLM sees only source IDs; page/document come from stored chunks.
8. **No LlamaIndex**; Docling optional behind the extractor interface.

# ADR-002: Vector backends (dev vs production)

Status: accepted (Phase 1)

The developer machine runs MongoDB Community 8.0, which has no `$vectorSearch`/`$search`.
`VECTOR_BACKEND=atlas` is the production path. `VECTOR_BACKEND=local` is a real but
dev-only implementation: workspace-filtered candidate scan with cosine similarity in
Python (hard-capped candidate count) plus a Mongo `$text` index for keyword search.
It is never selected automatically; the app logs which backend is active and
`scripts/verify_indexes.py` checks the Atlas indexes exist when `atlas` is selected.

# ADR-003: Object storage in development

`STORAGE_BACKEND=local` stores objects under `LOCAL_STORAGE_DIR` with random keys behind the same
`ObjectStore` interface as S3. Production uses `s3`.

# ADR-005: Background jobs (supersedes the sync-worker note in ADR-001 item 2)

Status: accepted (Phase 6)

- The pipeline is **async** (one implementation). Celery tasks call `asyncio.run(...)` and create their own
  `AsyncMongoClient` per task, so there is no second sync data layer.
- `JOB_BACKEND=celery` (Redis) is production. `JOB_BACKEND=inline` runs the same orchestrator as asyncio tasks in
  the API process for development without Redis. Jobs are checkpointed per stage in `processing_jobs`,
  so a re-run (retry, worker crash, recovery) skips completed stages.
- `recover_stuck_jobs` re-enqueues jobs left running by a dead process (Celery beat every 5 min; at API start
  for inline).
- Hosted embeddings send document text to a third party, so **upload and retry are blocked until a workspace admin
  grants `ai_processing_consent`** (when `EMBEDDING_PROVIDER` is not `local`).
- Uploaded content type is decided from file CONTENT (PDF header, DOCX zip structure with zip-bomb limits, text
  sniffing) and must match the extension. Object keys are server-generated; filenames are display-only.
