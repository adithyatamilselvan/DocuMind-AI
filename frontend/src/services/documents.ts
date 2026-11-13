import { api, type Query } from "@/lib/api";
import type { Collection, DocumentItem, DocumentPage, Overview } from "@/types";

export type DocumentFilters = {
  q?: string;
  status?: string;
  category?: string;
  tag?: string;
  collection_id?: string;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
};

export type BulkBody =
  | { action: "delete"; ids: string[] }
  | { action: "add_tags" | "remove_tags"; ids: string[]; tags: string[] }
  | { action: "add_to_collection" | "remove_from_collection"; ids: string[]; collection_id: string }
  | { action: "set_category"; ids: string[]; category: string | null };

const base = (ws: string) => `/workspaces/${ws}`;

export const documentService = {
  list: (ws: string, f: DocumentFilters) =>
    api<DocumentPage>(`${base(ws)}/documents`, { query: f as Query }),
  get: (ws: string, id: string) => api<DocumentItem>(`${base(ws)}/documents/${id}`),
  update: (
    ws: string,
    id: string,
    body: { title?: string; category?: string | null; tags?: string[]; collection_ids?: string[] },
  ) => api<DocumentItem>(`${base(ws)}/documents/${id}`, { method: "PATCH", body }),
  remove: (ws: string, id: string) => api(`${base(ws)}/documents/${id}`, { method: "DELETE" }),
  bulk: (ws: string, body: BulkBody) =>
    api<{ affected: number }>(`${base(ws)}/documents/bulk`, { body }),
  collections: (ws: string) => api<Collection[]>(`${base(ws)}/collections`),
  createCollection: (ws: string, name: string, parent_id?: string) =>
    api<Collection>(`${base(ws)}/collections`, { body: { name, parent_id } }),
  deleteCollection: (ws: string, id: string) =>
    api(`${base(ws)}/collections/${id}`, { method: "DELETE" }),
  overview: (ws: string) => api<Overview>(`${base(ws)}/analytics/overview`),
};
