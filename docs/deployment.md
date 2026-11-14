# Deployment

Status: the Dockerfiles and `docker-compose.yml` are written but **were not built or run** (Docker was not available during development). Treat the first
build as part of your acceptance test.

## 1. Prerequisites
| Service | Purpose | Notes |
|---|---|---|
| MongoDB **Atlas** | data + Vector Search + Atlas Search | M0 works for evaluation (3 search indexes total); required for `VECTOR_BACKEND=atlas` |
| Redis | Celery broker/result, shared rate limits | `JOB_BACKEND=celery`, `RATE_LIMIT_BACKEND=redis` |
| S3-compatible bucket | original files, extractions, report exports | private bucket; encryption at rest |
| Anthropic API key | answers, insights, research, comparison | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-opus-5-5`) |
| OpenAI API key | embeddings (default) | or `EMBEDDING_PROVIDER=local` with `pip install sentence-transformers` and `EMBEDDING_MODEL=BAAI/bge-m3` (~3-4 GB RAM) |
| SMTP | verification/reset emails | `EMAIL_BACKEND=smtp` (`log` is refused in production) |
| ClamAV (optional) | malware scanning | `MALWARE_SCAN=clamav`, `CLAMAV_HOST/PORT` |

## 2. Configure
Copy `.env.example` to `.env` and set at least: `APP_ENV=production`, `APP_SECRET_KEY`, `MONGODB_URI`, `MONGODB_DB`, `VECTOR_BACKEND=atlas`, `JOB_BACKEND=celery`,
`REDIS_URL`, `STORAGE_BACKEND=s3` + `S3_*`, provider keys, `FRONTEND_URL` (public https origin), `COOKIE_SECURE=true`, `TRUST_FORWARDED_FOR=true` (behind your proxy),
`EMAIL_BACKEND=smtp` + `SMTP_*`. Production refuses: `STORAGE_BACKEND=local`, `VECTOR_BACKEND=local`, `EMAIL_BACKEND=log`, `LLM_PROVIDER=fake`, `EMBEDDING_PROVIDER=hashing`.

## 3. Create and verify the search indexes (once per cluster, and after changing the embedding dimension)
```
cd backend
python scripts/verify_indexes.py --create --smoke     # creates chunks_vector + chunks_text, waits until queryable, runs a real $vectorSearch
```
`GET /health/ready` returns 503 until both indexes are queryable. Documents wait (retry) at the index stage until then.

## 4. Run
```
docker compose up -d redis minio minio-init              # infrastructure only
docker compose --profile app up -d --build               # api + celery worker + beat + frontend
```
Put a TLS-terminating reverse proxy in front of the frontend (port 3000). Proxy `/` to the frontend only; the API is reached via the frontend's `/api` rewrite.
Raise proxy body limits above `MAX_UPLOAD_MB`, disable response buffering for `text/event-stream` (the API sends `X-Accel-Buffering: no`), and set read timeouts above 60 s.
Scale workers with `docker compose --profile app up -d --scale worker=N`; `WORKER_CONCURRENCY`/`--concurrency` bound parallel ingestion; `LLM_CONCURRENCY` bounds parallel answers per API process.

## 5. Operations
- Health: `/health` (liveness), `/health/ready` (database, search indexes, Redis).
- Stuck work: Celery beat runs `recover_stuck_jobs` every 5 minutes. Failed documents can be retried from the UI/API (`POST .../documents/{id}/retry`), and a knowledge base can be reindexed.
- Logs never contain secrets or document text. Usage/cost by user and model: Settings → AI usage (admin) or `GET .../analytics/usage`.
- Backups: back up MongoDB and the bucket together. Chunks/embeddings are derivable from originals (reprocess), insights are regenerable.
- Re-embedding after a model change: bump `EMBEDDING_VERSION`, create a new vector index with the new dimension, then reindex knowledge bases/documents.
- Windows development setup: [setup-windows.md](setup-windows.md).
