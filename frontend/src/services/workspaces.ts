import { api } from "@/lib/api";
import type { Member, Role, Workspace } from "@/types";

export const workspaceService = {
  list: () => api<Workspace[]>("/workspaces"),
  create: (name: string) => api<Workspace>("/workspaces", { body: { name } }),
  update: (id: string, body: { name?: string; settings?: { ai_processing_consent: boolean } }) =>
    api<Workspace>(`/workspaces/${id}`, { method: "PATCH", body }),
  remove: (id: string) => api(`/workspaces/${id}`, { method: "DELETE" }),
  members: (id: string) => api<Member[]>(`/workspaces/${id}/members`),
  addMember: (id: string, body: { email: string; role: Role }) =>
    api<Member>(`/workspaces/${id}/members`, { body }),
  setRole: (id: string, userId: string, role: Role) =>
    api(`/workspaces/${id}/members/${userId}`, { method: "PATCH", body: { role } }),
  removeMember: (id: string, userId: string) =>
    api(`/workspaces/${id}/members/${userId}`, { method: "DELETE" }),
};
