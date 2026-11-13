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
- [ ] Phases 4-19: not started

## Test results (observed)
- Backend: `cd backend && .venv\Scripts\python -m pytest -q` -> 18 passed (auth, CSRF, rate limit, tenant isolation, RBAC)
- Ruff clean.

## Known limitations
- Rate limiter is in-process (swap to Redis in Phase 17).
- Adding members only works for already-registered users (no email invitations yet).
- Registration reveals whether an email exists (409); accepted UX trade-off.
- Workspace delete is soft; purge job comes with documents (Phase 6+).

## Next steps
Phase 4: Next.js frontend foundation, design system, auth pages.
