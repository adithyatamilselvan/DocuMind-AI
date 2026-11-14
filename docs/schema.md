# MongoDB schema

All `_id` are ObjectIds. Timestamps are UTC (`created_at`, `updated_at`). Tenant-owned collections carry `workspace_id` and every query
filters by it. Indexes are created idempotently at startup (`app/core/indexes.py`); Atlas Vector/Search indexes are managed by
`backend/scripts/verify_indexes.py` (see deployment). "Delete" = what happens when the owner/parent is deleted.

| Collection | Key fields | Indexes | Delete behaviour |
|---|---|---|---|
| `users` | email (lowercase, unique), password_hash (Argon2id), name, email_verified, status, preferences | unique email | account deletion removes it; audit/usage rows are anonymised |
| `sessions` | token_hash (SHA-256 of the cookie value), user_id, ip, user_agent, expires_at | unique token_hash; TTL expires_at | TTL / logout / password change |
| `password_reset_tokens`, `email_verification_tokens` | token_hash, user_id, expires_at, used_at | unique token_hash; TTL | TTL |
| `workspaces` | name, slug (unique), owner_id, settings{ai_processing_consent}, deleted_at | unique slug | **purged** (records + files) by `DELETE /workspaces/{id}` |
| `memberships` | workspace_id, user_id, role (viewer/editor/admin/owner), status | unique (workspace,user); user | removed with user/workspace; last owner protected |
| `documents` | workspace_id, owner_id, title, filename, mime_type, size_bytes, sha256, status, error, category, tags[], collection_ids[], page_count, language, current_version_id, version_count, extraction{}, access_count, deleted_at | (ws,status,created), (ws,sha256), (ws,tags), (ws,collection_ids), (ws,deleted_at) | soft-deleted; chunks, insights and derived artifacts removed immediately |
| `document_versions` | document_id, workspace_id, version_no, storage_key, sha256, size_bytes, mime_type, filename, page_count, chunk_count, extraction{} | unique (document,version_no) | with workspace purge; objects deleted |
| `collections` | workspace_id, name, parent_id | unique (ws,parent,name) | removed from documents on delete; must be empty of children |
| `document_chunks` | workspace_id, document_id, document_version_id, chunk_id (`{version}:{index}`, unique), chunk_index, content, **embedding**, page_number, section_heading, section_path, token_count, content_hash, embedding_model, embedding_version, is_current, metadata{type,ocr,page_basis} | unique (version,chunk_index); (ws,doc); (doc,version); text(content,section_heading) for local search; **Atlas vector `chunks_vector`** (embedding, filters workspace_id/document_id/is_current) and **Atlas search `chunks_text`** | deleted with the document; older versions removed when a new version is indexed |
| `document_insights` | workspace_id, document_id, document_version_id, kind="overview", status, payload (typed), structure, verification, model, prompt_version, schema_version | unique (version,kind) | with document |
| `knowledge_bases` | workspace_id, name, description, document_ids[], deleted_at | unique (ws,name) where not deleted | document ids pulled when a document is deleted |
| `conversations` | workspace_id, user_id, title, scope{document_ids,collection_ids,knowledge_base_ids,...}, message_count | (ws,user,updated) | hard delete cascades messages; private to the user |
| `messages` | conversation_id, workspace_id, user_id, role, content, citations[], meta{grounded,retrieval,usage,...}, feedback | (conversation,created); text(content) | with conversation |
| `processing_jobs` | workspace_id, type (ingest/insights/research/comparison/report), document_id/version_id or analysis_id/comparison_id/report_id, state, attempts, stages{}, progress, error | (ws,state); (state,updated); version | workspace purge |
| `research_analyses` | workspace_id, kind (paper/synthesis), title, document_ids[], version_ids[], status, result, verification | (ws,created) | removed when any source document is deleted |
| `document_comparisons` | workspace_id, kind (documents/versions), document_ids[], version_ids[], aspects, status, result, verification | (ws,created) | removed when a source document is deleted |
| `reports` | workspace_id, type, title, source{}, source_document_ids[], status, sections, references, exports[{format,storage_key,size}] | (ws,created) | removed with source documents; export objects deleted on explicit delete / purge |
| `audit_logs` | workspace_id, actor_id, action, target{}, ip, request_id | (ws,created) | kept; actor anonymised on account deletion |
| `usage_records` | workspace_id, user_id, kind, provider, model, tokens_in/out, latency_ms, meta | (ws,created); (ws,kind,created) | workspace purge; user anonymised |
| `search_history` | workspace_id, user_id, query, mode, filters, results | (ws,user,created) | with user/workspace |

## Atlas Vector Search
`numDimensions` must equal `EMBEDDING_DIM` (1024 by default). Changing embedding model/dimension requires a new index and re-embedding
(bump `EMBEDDING_VERSION`; chunks with other dimensions are ignored, never mixed). `scripts/verify_indexes.py --create --smoke` creates and
verifies both indexes; `/health/ready` reports them and returns 503 until queryable. The app never assumes an index exists.
