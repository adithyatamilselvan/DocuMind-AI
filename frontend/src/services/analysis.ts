import { api } from "@/lib/api";
import type { components } from "@/types/api";

type S = components["schemas"];
export type Analysis = S["AnalysisOut"];
export type Comparison = S["ComparisonOut"];
export type Report = S["ReportOut"];
export type ReportType = S["ReportIn"]["type"];

const w = (ws: string) => `/workspaces/${ws}`;

export const analysisService = {
  papers: (ws: string) => api<Analysis[]>(`${w(ws)}/research`),
  analysePaper: (ws: string, document_id: string) => api<Analysis>(`${w(ws)}/research/papers`, { body: { document_id } }),
  synthesise: (ws: string, document_ids: string[]) => api<Analysis>(`${w(ws)}/research/synthesis`, { body: { document_ids } }),
  comparisons: (ws: string) => api<Comparison[]>(`${w(ws)}/comparisons`),
  compare: (ws: string, document_ids: string[]) => api<Comparison>(`${w(ws)}/comparisons`, { body: { document_ids } }),
  compareVersions: (ws: string, document_id: string) => api<Comparison>(`${w(ws)}/comparisons/versions`, { body: { document_id } }),
  reports: (ws: string) => api<Report[]>(`${w(ws)}/reports`),
  report: (ws: string, id: string) => api<Report>(`${w(ws)}/reports/${id}`),
  createReport: (ws: string, body: { type: ReportType; document_ids?: string[]; analysis_id?: string; comparison_id?: string }) =>
    api<Report>(`${w(ws)}/reports`, { body }),
  deleteReport: (ws: string, id: string) => api(`${w(ws)}/reports/${id}`, { method: "DELETE" }),
  downloadUrl: (ws: string, id: string, format: "pdf" | "docx") => `/api/v1${w(ws)}/reports/${id}/download?format=${format}`,
};
