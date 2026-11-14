import { api } from "@/lib/api";
import type { components } from "@/types/api";

type S = components["schemas"];
export type Kb = S["KbOut"];
export type KbDetail = S["KbDetail"];
export type SearchOut = S["SearchOut"];
export type SearchHit = S["SearchHit"];
export type SearchHistoryItem = S["HistoryItem"];
export type SearchFilters = S["Filters"];

const w = (ws: string) => `/workspaces/${ws}`;

export const knowledgeService = {
  list: (ws: string) => api<Kb[]>(`${w(ws)}/knowledge-bases`),
  get: (ws: string, id: string) => api<KbDetail>(`${w(ws)}/knowledge-bases/${id}`),
  create: (ws: string, name: string, description = "") => api<Kb>(`${w(ws)}/knowledge-bases`, { body: { name, description } }),
  remove: (ws: string, id: string) => api(`${w(ws)}/knowledge-bases/${id}`, { method: "DELETE" }),
  addDocuments: (ws: string, id: string, document_ids: string[]) => api<Kb>(`${w(ws)}/knowledge-bases/${id}/documents`, { body: { document_ids } }),
  removeDocument: (ws: string, id: string, docId: string) => api(`${w(ws)}/knowledge-bases/${id}/documents/${docId}`, { method: "DELETE" }),
  reindex: (ws: string, id: string) => api<{ queued: number }>(`${w(ws)}/knowledge-bases/${id}/reindex`, { method: "POST" }),
  search: (ws: string, query: string, mode: "hybrid" | "semantic" | "keyword", filters: SearchFilters = {}) =>
    api<SearchOut>(`${w(ws)}/search`, { body: { query, mode, filters, limit: 20 } }),
  history: (ws: string) => api<SearchHistoryItem[]>(`${w(ws)}/search/history`),
  clearHistory: (ws: string) => api(`${w(ws)}/search/history`, { method: "DELETE" }),
};
