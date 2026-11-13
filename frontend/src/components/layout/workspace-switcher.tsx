"use client";

import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { useWorkspaceStore } from "@/stores/workspace";

export function WorkspaceSwitcher() {
  const { workspace, workspaces, isLoading } = useCurrentWorkspace();
  const setWorkspaceId = useWorkspaceStore((s) => s.setWorkspaceId);
  if (isLoading) return <Skeleton className="h-8 w-40" />;
  if (!workspace) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" className="max-w-52 gap-2" aria-label="Switch workspace" />
        }
      >
        <span className="truncate font-medium">{workspace.name}</span>
        <ChevronsUpDown className="size-3.5 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
          {workspaces?.map((w) => (
            <DropdownMenuItem key={w.id} onClick={() => setWorkspaceId(w.id)}>
              <span className="flex-1 truncate">{w.name}</span>
              {w.id === workspace.id && <Check className="size-4" aria-hidden />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
