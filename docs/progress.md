# DocuMind-AI progress

## Environment facts
- Windows 11, Python 3.11.9, Node 22, Git. MongoDB Community 8.0 running locally (no vector search).
- NOT installed: Docker, Redis, Tesseract, uv/pnpm. WSL has no distro.
- Backend venv: `backend/.venv`. Dev DB `documind_dev`, test DB `documind_test` (other DBs on this Mongo belong to other projects: never touch).

## Phases
- [x] Phase 0: architecture (see ADRs)
- [x] Phase 1: repo, config, `.env.example`, ADRs (docker-compose deferred to Phase 19: Docker not installed, can't be verified now)
- [x] Phase 2: FastAPI core (error envelope, request-id, Mongo async client, indexes for all collections, audit)
- [x] Phase 3: auth (Argon2id, hashed server-side sessions, HttpOnly cookie, HMAC CSRF + Origin check, rate limit,
  reset/verify email flows), workspaces, memberships, RBAC (viewer<editor<admin<owner), last-owner guard
- [x] Phase 4: Next.js app, design tokens (light/dark), providers, API client (CSRF, error envelope, expiry handling),
  auth pages (login/register/forgot/reset/verify), collapsible sidebar + mobile sheet nav, workspace switcher,
  Dashboard (workspace overview only; real document metrics arrive in Phase 5/16), Workspace members page, Settings
  (profile, theme, password, AI-processing consent)
- [x] Phase 5: documents module (list/filter/sort/paginate, patch, bulk, soft-delete + immediate chunk/insight purge,
  validated status state machine), collections (tree, counts), analytics overview (all real queries), frontend
  dashboard (KPIs, usage chart, categories, top docs, activity), document library + detail pages
- [ ] Phases 6-19: not started

## Test results (observed)
- Backend: `cd backend && .venv\Scripts\python -m pytest -q` -> 30 passed (auth, CSRF, rate limit, tenant isolation, RBAC, documents, collections, analytics)
- Ruff clean.
- Frontend (run in PowerShell, NOT Git Bash: npm scripts fail to find `node` there):
  `npx vitest run` -> 14 passed; `npx tsc --noEmit` clean; `npx eslint src e2e` clean; `npm run build` succeeds;
  `npx playwright test` -> 14 passed (auth flow, validation, settings, dashboard, library empty/filter/404; desktop Chrome + Pixel 7 viewport,
  includes a no-horizontal-overflow assertion). E2E uses DB `documind_e2e`, ports 8100/3100.

## Known limitations
- Rate limiter is in-process (swap to Redis in Phase 17).
- Adding members only works for already-registered users (no email invitations yet).
- Registration reveals whether an email exists (409); accepted UX trade-off.
- Workspace delete is soft; purge job comes with documents (Phase 6+).

## Next steps
Phase 6: upload, object storage, job queue/orchestrator. Library rows are not e2e-tested until upload exists.

## Windows notes
- Use PowerShell for npm/npx. Git Bash cannot launch Node subprocesses spawned via cmd.
- `.env` at repo root is gitignored; backend reads `../.env`. Create from `.env.example`.

## PyMongo async gotcha
`collection.aggregate()` is a coroutine returning a cursor: use `async for x in await coll.aggregate(...)`. `find()` is not.
