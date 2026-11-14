# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `npm`/`npx` fails with `'"node"' is not recognized` | Run frontend commands in **PowerShell**, not Git Bash. |
| Upload returns `403 ai_consent_required` | A workspace admin must tick "Allow external AI processing" in Settings (only needed when an external AI provider is configured). |
| Document ends `FAILED: The embedding provider is not configured on the server` | Set `OPENAI_API_KEY` (or use `EMBEDDING_PROVIDER=local`, or `hashing` for offline demos). Then **Retry processing**. |
| Insights say "AI insights are not configured on this server" | Set `ANTHROPIC_API_KEY`. Documents still complete without it; regenerate insights afterwards. |
| Chat/ask returns 503 `llm_not_configured` | Same: `ANTHROPIC_API_KEY` (or `LLM_PROVIDER=fake` for offline demos). |
| `FAILED: This looks like a scanned document but OCR is not available` | Install Tesseract (see setup-windows.md) or use the Docker image; set `TESSERACT_CMD`. Mixed documents continue with a warning. |
| `FAILED: The PDF is password protected` | Remove the password and upload a new version. |
| Documents stay QUEUED | `JOB_BACKEND=celery` needs a running worker (`celery -A app.workers.celery_app worker --pool=solo` on Windows). With `inline`, restart the API: unfinished jobs are re-queued at startup. |
| `/health/ready` is 503 | Search indexes missing or not queryable: run `scripts/verify_indexes.py --create`. Redis down if `JOB_BACKEND=celery`. |
| Semantic search finds nothing but keyword works | Embedding dimension/model mismatch (chunks with other dimensions are ignored) or `RAG_MIN_VECTOR_SCORE` too high for the model; check `EMBEDDING_DIM`, rebuild the Atlas index. |
| 429 on login/registration while testing | Rate limits (10 logins / 5 min per IP). Tests disable them with `RATE_LIMIT_ENABLED=false`. |
| Redirect loop `/login` ↔ `/dashboard` | Stale cookie: the app clears it via `/login?expired=1`; clear site cookies if it persists. |
| 403 "Missing or invalid CSRF token" from custom clients | Send the `documind_csrf` cookie value as `X-CSRF-Token` on unsafe requests, and a matching `Origin`. |
| PDF viewer blank in production | CSP must allow `worker-src blob:` and same-origin scripts; check the browser console, run `node e2e/prod-smoke.mjs`. |
| `IndexOptionsConflict` at startup | Handled automatically (conflicting index is dropped and recreated); if it persists, drop the named index manually. |
