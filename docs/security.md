# Security

## Implemented (and tested unless noted)
- **Passwords**: Argon2id; constant-time login (dummy verify for unknown users); policy 10-128 chars mixing character classes.
- **Sessions**: opaque random token in an HttpOnly, SameSite=Lax cookie (`Secure` when `COOKIE_SECURE=true`); only its SHA-256 is stored; 14-day TTL;
  password change/reset revokes other sessions; logout deletes the session.
- **CSRF**: HMAC double-submit (`X-CSRF-Token` = HMAC(secret, session token)) on every authenticated unsafe request + `Origin` allow-list.
- **CORS**: closed by default (same-origin proxy); explicit `CORS_ORIGINS` only.
- **Rate limiting**: auth endpoints and chat. In-process by default; `RATE_LIMIT_BACKEND=redis` for multiple replicas (fixed window, tested with a faithful fake; not run against real Redis).
- **Headers**: API and frontend send nosniff, frame denial, referrer/permissions policy; HSTS when `COOKIE_SECURE`; strict CSP on the production frontend
  (verified: no violations with the PDF viewer, `e2e/prod-smoke.mjs`). `script-src` needs `'unsafe-inline'` for Next.js bootstrap (no nonce setup).
- **Request limits**: JSON bodies > 2 MB rejected; uploads capped per file (`MAX_UPLOAD_MB`) and per request (`MAX_FILES_PER_UPLOAD`).
- **Uploads**: type decided from content (PDF header, DOCX package structure with zip-bomb limits, text sniffing) and must match the extension; client MIME is ignored;
  filenames sanitised and display-only; object keys are server-generated; storage is private (no public URLs; downloads stream through the API with `nosniff`).
- **Malware scanning**: optional ClamAV (`MALWARE_SCAN=clamav`), **fails closed** when the scanner is unreachable. Tested against an in-test clamd protocol server; not against a real ClamAV.
- **Tenant isolation**: every tenant query filters `workspace_id`; non-members get 404; retrieval scope is resolved server-side and intersected with the workspace; tests cover every module.
- **RBAC**: viewer < editor < admin < owner enforced by FastAPI dependencies; last-owner protection; owners-only role grants.
- **Prompt-injection defences**: documents are untrusted: their text is HTML-escaped inside `<source>`/`<document>` blocks (cannot forge sources), system rules override document content,
  structured outputs are schema-validated, and citations/quotes/pages are verified against stored text. Model output is rendered as inert text (no HTML).
- **External AI disclosure**: workspace-level consent (`ai_processing_consent`) is required before any document text goes to an external provider (uploads, chat, search, insights, research...).
- **Secrets**: only from environment variables; `SecretStr` in settings (not in repr); API keys are never sent to the browser; no secrets/document text in logs or usage records.
- **Audit**: security-relevant actions are logged (login/failed login with a hashed email, uploads, deletes, member changes, KB/report/analysis creation); admins can read them.
- **Privacy**: JSON data export, account deletion (password required), workspace purge removes records **and** stored files.

## Known limitations / operator responsibilities
- PDF/DOCX parsing runs in the worker process: run workers unprivileged with resource limits (the Dockerfile uses a non-root user); a parser exploit is the main residual risk.
- No email-verification enforcement (verification is recorded, not required to log in) and no MFA/SSO.
- The registration endpoint reveals whether an email exists (409). Rate limited.
- Add members only works for registered users (no emailed invitations).
- Object-store files of deleted documents are removed on workspace purge/report delete; individual document deletion removes DB content immediately but the
  original file object is not yet purged by a background job (records are gone, so it is unreachable through the API; schedule a lifecycle rule or sweep job).
- Terminate TLS at a reverse proxy, set `COOKIE_SECURE=true`, `TRUST_FORWARDED_FOR=true` only behind that proxy, and restrict `FRONTEND_URL`.
- Enable encryption at rest on the bucket and MongoDB; rotate `APP_SECRET_KEY` (invalidates CSRF tokens only) and provider keys regularly.
