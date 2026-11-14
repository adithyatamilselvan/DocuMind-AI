"""Generate docs/api.md from the FastAPI OpenAPI schema (method, route, auth, schemas, errors)."""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_SECRET_KEY", "openapi-export-only-secret-key-0123456789")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

spec = create_app().openapi()
root = Path(__file__).resolve().parents[2] / "docs"
(root / "openapi.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")


def ref(schema: dict | None) -> str:
    if not schema:
        return "-"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"{ref(schema.get('items'))}[]"
    return schema.get("type", "object")


PUBLIC = {"/health", "/health/ready", "/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/forgot-password",
          "/api/v1/auth/reset-password", "/api/v1/auth/verify-email"}  # fmt: skip
groups: dict[str, list[str]] = {}
for path, methods in sorted(spec["paths"].items()):
    for method, op in methods.items():
        tag = (op.get("tags") or ["other"])[0]
        body = op.get("requestBody", {}).get("content", {})
        req = ref(next(iter(body.values()), {}).get("schema")) if body else "-"
        if "multipart/form-data" in body:
            req = "multipart/form-data"
        ok = next((c for c in op["responses"] if c.startswith("2")), "200")
        resp_content = op["responses"][ok].get("content", {})
        resp = ref(next(iter(resp_content.values()), {}).get("schema")) if resp_content else "-"
        if "text/event-stream" in resp_content or "stream" in op.get("summary", "").lower():
            resp = "text/event-stream"
        params = ", ".join(p["name"] for p in op.get("parameters", []) if p["in"] == "query") or "-"
        if path in PUBLIC:
            auth = "none"
        elif "{workspace_id}" in path:
            auth = "session + role (see below)"
        else:
            auth = "session"
        mut = (
            "yes"
            if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and path not in PUBLIC
            else "no"
        )
        groups.setdefault(tag, []).append(
            f"| `{method.upper()}` | `{path}` | {auth} | {mut} | {req} | {ok} {resp} | {params} |"
        )

lines = [
    "# API reference",
    "",
    "Generated from the FastAPI OpenAPI schema by `backend/scripts/gen_api_docs.py` (do not edit by hand).",
    "Interactive docs: `/docs` on the API (disabled when `APP_ENV=production`). Machine-readable: `docs/openapi.json`.",
    "",
    "## Conventions",
    "- **Auth**: HttpOnly session cookie `documind_session`. Unsafe methods (POST/PUT/PATCH/DELETE) on authenticated routes also need the "
    "`X-CSRF-Token` header (value of the readable `documind_csrf` cookie) and, if `Origin` is sent, an allowed origin.",
    "- **Roles** on `/workspaces/{workspace_id}/...`: `viewer` < `editor` < `admin` < `owner`. Reads need viewer; document/KB/analysis/report writes "
    "need editor; audit log, usage and member management need admin; deleting a workspace needs owner. Non-members get **404**, insufficient role **403**.",
    '- **Errors**: `{"error": {"code", "message", "details", "request_id"}}`. 401 unauthenticated, 403 forbidden/CSRF/consent, 404 not found '
    "(also for foreign tenants), 409 conflict/state, 413 too large, 422 validation, 429 rate limited (`Retry-After`), 503 AI/scan unavailable.",
    "- **Pagination**: `?page=&page_size=` (max 100) -> `{items, total, page, page_size}`.",
    "- **Streaming**: `POST .../conversations/{id}/messages` and `.../regenerate` return `text/event-stream` with events "
    "`user_message`, `title`, `status`, `retrieval`, `token`, `final`, `error`, `done`.",
    "- **AI consent**: endpoints that send document text to an external AI provider return `403 ai_consent_required` until a workspace admin "
    "enables it in Settings.",
    "",
]
for tag, rows in sorted(groups.items()):
    lines += [
        f"## {tag}",
        "",
        "| Method | Route | Auth | CSRF | Request | Response | Query |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
(root / "api.md").write_text("\n".join(lines), encoding="utf-8")
print(f"wrote docs/api.md ({sum(len(r) for r in groups.values())} operations)")
