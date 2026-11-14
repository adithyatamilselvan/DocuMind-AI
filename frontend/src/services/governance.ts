import { api } from "@/lib/api";
import type { components } from "@/types/api";

type S = components["schemas"];
export type AuditPage = S["Page_AuditEntry_"];
export type Usage = S["UsageOut"];

export const governanceService = {
  audit: (ws: string, page: number, action?: string) =>
    api<AuditPage>(`/workspaces/${ws}/analytics/audit-logs`, { query: { page, page_size: 25, action } }),
  usage: (ws: string, days = 30) => api<Usage>(`/workspaces/${ws}/analytics/usage`, { query: { days } }),
  exportUrl: "/api/v1/users/me/export",
  deleteAccount: (password: string) => api("/users/me", { method: "DELETE", body: { password } }),
};
