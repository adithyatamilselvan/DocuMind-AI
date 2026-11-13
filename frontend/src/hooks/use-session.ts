"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { authService } from "@/services/auth";
import { workspaceService } from "@/services/workspaces";
import { useWorkspaceStore } from "@/stores/workspace";

export const keys = {
  me: ["me"] as const,
  workspaces: ["workspaces"] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: authService.me, staleTime: 60_000, retry: false });
}

export function useWorkspaces() {
  return useQuery({ queryKey: keys.workspaces, queryFn: workspaceService.list, staleTime: 30_000 });
}

/** The active workspace: the persisted selection if still valid, else the first one. */
export function useCurrentWorkspace() {
  const { data: workspaces, ...rest } = useWorkspaces();
  const { workspaceId, setWorkspaceId } = useWorkspaceStore();
  const workspace = workspaces?.find((w) => w.id === workspaceId) ?? workspaces?.[0];
  useEffect(() => {
    if (workspace && workspace.id !== workspaceId) setWorkspaceId(workspace.id);
  }, [workspace, workspaceId, setWorkspaceId]);
  return { workspace, workspaces, ...rest };
}
