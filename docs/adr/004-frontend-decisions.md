# ADR-004: Frontend decisions (Phase 4)

- **Next.js 16.4 / React 19 / Tailwind 4.** This Next version's own docs (`frontend/node_modules/next/dist/docs`)
  are authoritative; `AGENTS.md` instructs to read them before using any API.
- **`middleware` is now `proxy.ts`.** It only does optimistic redirects by cookie presence. The backend is the
  authorization boundary. The matcher excludes `/api` so uploads are never buffered/truncated by the proxy
  layer (`proxyClientMaxBodySize` defaults to 10MB and silently truncates).
- **`cacheComponents` is OFF.** The scaffold enabled it; the app is client-driven (TanStack Query) and
  Cache Components' Suspense/Activity semantics add friction without benefit. Revisit only if needed.
- **/api rewrite** to FastAPI (`BACKEND_INTERNAL_URL`) keeps cookies first-party; no CORS needed.
- **shadcn "base-nova" style (Base UI primitives)**, not Radix: triggers use the `render` prop, not `asChild`.
  `cn` comes from the `cn` package re-exported via `@/lib/utils`.
- **Stale cookie loop guard**: on a 401 the client navigates to `/login?expired=1`; the proxy then clears the
  HttpOnly cookies (JS cannot).
- **Contract sync**: `docs/openapi.json` (exported by `backend/scripts/export_openapi.py`) ->
  `npm run gen:api` -> `src/types/api.d.ts`. Re-run both after changing backend schemas.
- Native `<select>` is used for simple selects (accessible, mobile-friendly).
