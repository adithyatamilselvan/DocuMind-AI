# API reference

Generated from the FastAPI OpenAPI schema by `backend/scripts/gen_api_docs.py` (do not edit by hand).
Interactive docs: `/docs` on the API (disabled when `APP_ENV=production`). Machine-readable: `docs/openapi.json`.

## Conventions
- **Auth**: HttpOnly session cookie `documind_session`. Unsafe methods (POST/PUT/PATCH/DELETE) on authenticated routes also need the `X-CSRF-Token` header (value of the readable `documind_csrf` cookie) and, if `Origin` is sent, an allowed origin.
- **Roles** on `/workspaces/{workspace_id}/...`: `viewer` < `editor` < `admin` < `owner`. Reads need viewer; document/KB/analysis/report writes need editor; audit log, usage and member management need admin; deleting a workspace needs owner. Non-members get **404**, insufficient role **403**.
- **Errors**: `{"error": {"code", "message", "details", "request_id"}}`. 401 unauthenticated, 403 forbidden/CSRF/consent, 404 not found (also for foreign tenants), 409 conflict/state, 413 too large, 422 validation, 429 rate limited (`Retry-After`), 503 AI/scan unavailable.
- **Pagination**: `?page=&page_size=` (max 100) -> `{items, total, page, page_size}`.
- **Streaming**: `POST .../conversations/{id}/messages` and `.../regenerate` return `text/event-stream` with events `user_message`, `title`, `status`, `retrieval`, `token`, `final`, `error`, `done`.
- **AI consent**: endpoints that send document text to an external AI provider return `403 ai_consent_required` until a workspace admin enables it in Settings.

## analytics

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/analytics/audit-logs` | session + role (see below) | no | - | 200 Page_AuditEntry_ | action, actor_id, page, page_size |
| `GET` | `/api/v1/workspaces/{workspace_id}/analytics/overview` | session + role (see below) | no | - | 200 Overview | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/analytics/usage` | session + role (see below) | no | - | 200 UsageOut | days |

## auth

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/forgot-password` | none | no | ForgotPasswordIn | 202 - | - |
| `POST` | `/api/v1/auth/login` | none | no | LoginIn | 200 UserOut | - |
| `POST` | `/api/v1/auth/logout` | session | yes | - | 204 - | - |
| `GET` | `/api/v1/auth/me` | session | no | - | 200 UserOut | - |
| `POST` | `/api/v1/auth/register` | none | no | RegisterIn | 201 UserOut | - |
| `POST` | `/api/v1/auth/resend-verification` | session | yes | - | 202 - | - |
| `POST` | `/api/v1/auth/reset-password` | none | no | ResetPasswordIn | 204 - | - |
| `POST` | `/api/v1/auth/verify-email` | none | no | VerifyEmailIn | 204 - | - |

## chat

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/conversations` | session + role (see below) | no | - | 200 ConversationOut[] | q |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations` | session + role (see below) | yes | CreateConversationIn | 201 ConversationOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | session + role (see below) | no | - | 200 ConversationDetail | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | session + role (see below) | yes | UpdateConversationIn | 200 ConversationOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | session + role (see below) | yes | - | 204 - | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | session + role (see below) | yes | SendMessageIn | 200 - | - |
| `PUT` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/feedback` | session + role (see below) | yes | FeedbackIn | 204 - | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/regenerate` | session + role (see below) | yes | - | 200 - | - |

## collections

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/collections` | session + role (see below) | no | - | 200 CollectionOut[] | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/collections` | session + role (see below) | yes | CreateCollectionIn | 201 CollectionOut | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/collections/{collection_id}` | session + role (see below) | yes | UpdateCollectionIn | 200 CollectionOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/collections/{collection_id}` | session + role (see below) | yes | - | 204 - | - |

## comparison

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/workspaces/{workspace_id}/comparisons` | session + role (see below) | yes | CompareIn | 202 ComparisonOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/comparisons` | session + role (see below) | no | - | 200 ComparisonOut[] | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/comparisons/versions` | session + role (see below) | yes | VersionsIn | 202 ComparisonOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/comparisons/{comparison_id}` | session + role (see below) | no | - | 200 ComparisonOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/comparisons/{comparison_id}` | session + role (see below) | yes | - | 204 - | - |

## documents

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/documents` | session + role (see below) | no | - | 200 Page_DocumentOut_ | q, status, category, tag, collection_id, mime_type, created_from, created_to, sort, order, page, page_size |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/bulk` | session + role (see below) | yes | BulkIn | 200 BulkOut | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/upload` | session + role (see below) | yes | multipart/form-data | 200 UploadOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | session + role (see below) | no | - | 200 DocumentOut | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | session + role (see below) | yes | UpdateDocumentIn | 200 DocumentOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | session + role (see below) | yes | - | 204 - | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/download` | session + role (see below) | no | - | 200 - | version, inline |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/processing` | session + role (see below) | no | - | 200 object | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/retry` | session + role (see below) | yes | - | 202 - | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/text` | session + role (see below) | no | - | 200 DocumentTextOut | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/versions` | session + role (see below) | yes | multipart/form-data | 200 UploadResultOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/versions` | session + role (see below) | no | - | 200 VersionOut[] | - |

## insights

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/insights` | session + role (see below) | no | - | 200 InsightsOut | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}/insights` | session + role (see below) | yes | - | 202 - | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/insights` | session + role (see below) | no | - | 200 InsightSummary[] | category, limit |
| `GET` | `/api/v1/workspaces/{workspace_id}/suggestions` | session + role (see below) | no | - | 200 string[] | - |

## knowledge-bases

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/knowledge-bases` | session + role (see below) | no | - | 200 KbOut[] | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/knowledge-bases` | session + role (see below) | yes | KbIn | 201 KbOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}` | session + role (see below) | no | - | 200 KbDetail | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}` | session + role (see below) | yes | KbPatch | 200 KbOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}` | session + role (see below) | yes | - | 204 - | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents` | session + role (see below) | yes | AddDocsIn | 200 KbOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/documents/{document_id}` | session + role (see below) | yes | - | 204 - | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}/reindex` | session + role (see below) | yes | - | 202 - | - |

## privacy

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `DELETE` | `/api/v1/users/me` | session | yes | DeleteAccountIn | 204 - | - |
| `GET` | `/api/v1/users/me/export` | session | no | - | 200 - | - |

## rag

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/workspaces/{workspace_id}/ask` | session + role (see below) | yes | AskIn | 200 AskOut | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/search` | session + role (see below) | yes | SearchIn | 200 SearchOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/search/history` | session + role (see below) | no | - | 200 HistoryItem[] | limit |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/search/history` | session + role (see below) | yes | - | 204 - | - |

## reports

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/workspaces/{workspace_id}/reports` | session + role (see below) | yes | ReportIn | 202 ReportOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/reports` | session + role (see below) | no | - | 200 ReportOut[] | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/reports/{report_id}` | session + role (see below) | no | - | 200 ReportOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/reports/{report_id}` | session + role (see below) | yes | - | 204 - | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/reports/{report_id}/download` | session + role (see below) | no | - | 200 - | format |

## research

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/research` | session + role (see below) | no | - | 200 AnalysisOut[] | kind |
| `POST` | `/api/v1/workspaces/{workspace_id}/research/papers` | session + role (see below) | yes | PaperIn | 202 AnalysisOut | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/research/synthesis` | session + role (see below) | yes | SynthesisIn | 202 AnalysisOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/research/{analysis_id}` | session + role (see below) | no | - | 200 AnalysisOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/research/{analysis_id}` | session + role (see below) | yes | - | 204 - | - |

## system

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/system/config` | session | no | - | 200 ClientConfig | - |
| `GET` | `/health` | none | no | - | 200 - | - |
| `GET` | `/health/ready` | none | no | - | 200 - | - |

## users

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `PATCH` | `/api/v1/users/me` | session | yes | UpdateProfileIn | 200 UserOut | - |
| `POST` | `/api/v1/users/me/password` | session | yes | ChangePasswordIn | 204 - | - |

## workspaces

| Method | Route | Auth | CSRF | Request | Response | Query |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/workspaces` | session | no | - | 200 WorkspaceOut[] | - |
| `POST` | `/api/v1/workspaces` | session | yes | CreateWorkspaceIn | 201 WorkspaceOut | - |
| `GET` | `/api/v1/workspaces/{workspace_id}` | session + role (see below) | no | - | 200 WorkspaceOut | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}` | session + role (see below) | yes | UpdateWorkspaceIn | 200 WorkspaceOut | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}` | session + role (see below) | yes | - | 204 - | - |
| `GET` | `/api/v1/workspaces/{workspace_id}/members` | session + role (see below) | no | - | 200 MemberOut[] | - |
| `POST` | `/api/v1/workspaces/{workspace_id}/members` | session + role (see below) | yes | AddMemberIn | 201 MemberOut | - |
| `PATCH` | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | session + role (see below) | yes | UpdateMemberIn | 204 - | - |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/members/{user_id}` | session + role (see below) | yes | - | 204 - | - |
