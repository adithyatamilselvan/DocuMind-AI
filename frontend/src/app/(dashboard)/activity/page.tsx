"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounced } from "@/hooks/use-debounced";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { governanceService } from "@/services/governance";
import { atLeast } from "@/types";

export default function ActivityPage() {
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const isAdmin = atLeast(workspace?.role, "admin");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const action = useDebounced(filter);
  const q = useQuery({
    queryKey: ["audit", ws, page, action], queryFn: () => governanceService.audit(ws!, page, action || undefined),
    enabled: !!ws && isAdmin, placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 25));

  if (workspace && !isAdmin) return <p className="text-sm text-muted-foreground">The activity history is available to workspace admins.</p>;
  return (
    <>
      <PageHeader title="Activity history" description="Who did what in this workspace." />
      <Input aria-label="Filter by action" placeholder="Filter by action, e.g. document." className="mb-4 max-w-xs" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} />
      {q.isLoading ? <Skeleton className="h-48" /> : q.isError ? <p role="alert" className="text-sm text-destructive">{errorMessage(q.error)}</p> : (
        <>
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Who</TableHead><TableHead>Action</TableHead><TableHead className="hidden md:table-cell">Details</TableHead></TableRow></TableHeader>
              <TableBody>
                {q.data?.items.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(e.created_at)}</TableCell>
                    <TableCell>{e.actor_name ?? "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{e.action}</TableCell>
                    <TableCell className="hidden max-w-80 truncate text-xs text-muted-foreground md:table-cell">{Object.keys(e.target).length ? JSON.stringify(e.target) : ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <nav aria-label="Pagination" className="mt-3 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Page {page} of {pages} · {q.data?.total} events</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </nav>
        </>
      )}
    </>
  );
}
