# DocuMind AI

Document intelligence and research assistant: upload PDF/DOCX/TXT, extract and index them, search them (full-text, semantic, hybrid),
ask questions with **validated citations**, analyse research papers, compare documents and versions, and export PDF/DOCX reports.

- **Backend**: FastAPI + PyMongo Async (modular monolith), Celery/Redis jobs, S3-compatible storage, MongoDB Atlas Vector Search.
- **Frontend**: Next.js 16 (App Router), TypeScript strict, Tailwind 4, shadcn/ui (Base UI), TanStack Query.
- **AI**: Anthropic Claude (official SDK) for generation; hosted OpenAI embeddings by default (local bge-m3 behind the same interface).

Docs: [architecture](docs/architecture.md) · [schema](docs/schema.md) · [API](docs/api.md) · [security](docs/security.md) ·
[deployment](docs/deployment.md) · [Windows setup](docs/setup-windows.md) · [troubleshooting](docs/troubleshooting.md) ·
[progress and known limitations](docs/progress.md) · [ADRs](docs/adr/)

## What is verified and what is not

Everything below was run and observed on a Windows dev machine (MongoDB Community 8.0, no Docker/Redis/Tesseract/API keys):
backend `pytest` (229 tests), frontend `vitest` (28), Playwright e2e on desktop + mobile viewports, production-build smoke test under the CSP.
Tests that need paid or external services use **real code paths with faked providers** (scripted/extractive LLM, deterministic hashing embedder,
local vector scan, in-test clamd server). **Not verified against the real services** (needs your credentials/infrastructure):
Anthropic and OpenAI calls, Atlas `$vectorSearch`/`$search`, Redis/Celery workers, S3/MinIO, Docker images, real Tesseract OCR, ClamAV.
See [docs/progress.md](docs/progress.md#manual-setup-still-required) for the exact checklist.

## Quick start (development, no Docker)

Requirements: Python 3.11+, Node 22+, a running MongoDB.

```powershell
# 1. configuration
copy .env.example .env          # set APP_SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(48))")

# 2. backend
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 3. frontend (new terminal; use PowerShell, not Git Bash, for npm on Windows)
cd frontend
npm install
npm run dev                      # http://localhost:3000 (proxies /api to :8000)
```

Defaults run **without Docker or Redis**: jobs run inside the API process (`JOB_BACKEND=inline`), files go to `.local-data/`
(`STORAGE_BACKEND=local`), vector search uses a bounded scan on plain MongoDB (`VECTOR_BACKEND=local`).
To process real documents you need embeddings and an LLM:

| Goal | Set |
|---|---|
| Real answers | `ANTHROPIC_API_KEY=...` (model defaults to `claude-opus-5-5`, change with `ANTHROPIC_MODEL`) |
| Real embeddings | `OPENAI_API_KEY=...` (default `EMBEDDING_PROVIDER=openai`, `text-embedding-3-large` at 1024 dims) |
| Offline demo without keys | `EMBEDDING_PROVIDER=hashing` and `LLM_PROVIDER=fake` (deterministic, **no semantic understanding**; blocked when `APP_ENV=production`) |

After registering, a workspace admin must enable **external AI processing** in Settings (explicit consent) before documents are processed
by an external provider.

## Production-like setup

See [docs/deployment.md](docs/deployment.md): MongoDB Atlas (`VECTOR_BACKEND=atlas` + `python backend/scripts/verify_indexes.py --create --smoke`),
Redis + Celery (`JOB_BACKEND=celery`), S3/MinIO, `docker compose --profile app up -d --build`.

## Tests

```powershell
cd backend;  .venv\Scripts\python -m pytest -q                 # ~3-4 min, needs local MongoDB (uses DB documind_test)
cd backend;  .venv\Scripts\python -m ruff check .
cd frontend; npx tsc --noEmit; npx eslint src e2e; npx vitest run
cd frontend; npx playwright test                              # starts API (:8100) + Next dev (:3100); DB documind_e2e
cd frontend; npm run build; node e2e/prod-smoke.mjs           # production build + CSP smoke (see header of the file)
```

Opt-in live-provider tests belong under the `integration` marker (`pytest -m integration`); none are enabled by default.
After changing backend schemas: `python backend/scripts/gen_api_docs.py` then `npm run gen:api` in `frontend/`.

## Repository layout

```
backend/app/{core,middleware,api/v1,ai/{providers,prompts},storage,workers,modules/<feature>}   backend/{tests,evals,scripts}
frontend/src/{app,components,services,hooks,lib,types,stores,schemas}   frontend/e2e
docs/   docker-compose.yml   .env.example
```
