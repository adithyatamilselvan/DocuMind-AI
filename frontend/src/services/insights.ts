import { api } from "@/lib/api";
import type { InsightSummary, InsightsOut } from "@/types";

/** Shapes of `InsightsOut.payload`, validated server-side by Pydantic (backend/app/modules/insights/schemas.py). */
export type Finding = { text: string; page: number | null; quote: string | null };
export type InsightPayload = {
  summary: string;
  executive_summary: string;
  key_findings: Finding[];
  key_facts: Finding[];
  topics: string[];
  keywords: string[];
  classification: { document_type: string; category: string; confidence: "low" | "medium" | "high" };
  entities: { people: string[]; organizations: string[]; locations: string[] };
  important_dates: { date: string; description: string; page: number | null }[];
  main_arguments: Finding[];
  conclusions: Finding[];
  limitations: Finding[];
  action_items: string[];
  suggested_questions: string[];
};
export type Structure = {
  page_basis: "physical" | "virtual";
  page_count: number;
  outline: { level: number; title: string; page: number }[];
  tables: { page: number; rows: number; columns: number; preview: string[][] }[];
  ocr_pages: number[];
};

export const insightsService = {
  get: (ws: string, id: string) => api<InsightsOut>(`/workspaces/${ws}/documents/${id}/insights`),
  regenerate: (ws: string, id: string) => api(`/workspaces/${ws}/documents/${id}/insights`, { method: "POST" }),
  list: (ws: string, category?: string) =>
    api<InsightSummary[]>(`/workspaces/${ws}/insights`, { query: { category } }),
  suggestions: (ws: string) => api<string[]>(`/workspaces/${ws}/suggestions`),
};
