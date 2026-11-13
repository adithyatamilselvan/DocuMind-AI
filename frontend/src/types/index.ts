import type { components } from "./api";

type S = components["schemas"];
export type User = S["UserOut"];
export type Workspace = S["WorkspaceOut"];
export type Member = S["MemberOut"];
export type Role = Workspace["role"];
export type DocumentItem = S["DocumentOut"];
export type DocumentStatus = DocumentItem["status"];
export type DocumentPage = S["Page_DocumentOut_"];
export type Collection = S["CollectionOut"];
export type Overview = S["Overview"];

export const ROLE_RANK: Record<Role, number> = { viewer: 1, editor: 2, admin: 3, owner: 4 };
export const atLeast = (role: Role | undefined, min: Role) =>
  !!role && ROLE_RANK[role] >= ROLE_RANK[min];
