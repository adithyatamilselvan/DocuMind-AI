"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileText, Search, Tag, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { StatusBadge, isInProgress } from "@/components/documents/status-badge";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDebounced } from "@/hooks/use-debounced";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import { documentService } from "@/services/documents";
import { atLeast, type DocumentStatus } from "@/types";

const STATUSES: DocumentStatus[] = ["COMPLETED", "FAILED", "QUEUED", "PROCESSING", "UPLOADING"];
const SORTS = [
  ["created_at:desc", "Newest first"],
  ["created_at:asc", "Oldest first"],
  ["title:asc", "Title A–Z"],
  ["size_bytes:desc", "Largest first"],
  ["access_count:desc", "Most opened"],
] as const;

export default function DocumentsPage() {
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canEdit = atLeast(workspace?.role, "editor");

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [tag, setTag] = useState("");
  const [sort, setSort] = useState<string>(SORTS[0][0]);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [bulkTag, setBulkTag] = useState("");
  const q = useDebounced(search);
  const tagFilter = useDebounced(tag);

  const [sortField, order] = sort.split(":") as [string, "asc" | "desc"];
  const filters = {
    q: q || undefined, status: status || undefined, tag: tagFilter || undefined,
    sort: sortField, order, page, page_size: 20,
  }; // fmt: skip

  const list = useQuery({
    queryKey: ["documents", ws, filters],
    queryFn: () => documentService.list(ws!, filters),
    enabled: !!ws,
    placeholderData: keepPreviousData,
    // Poll while anything is still being processed so status badges update live.
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => isInProgress(d.status)) ? 3000 : false,
  });

  const afterChange = () => {
    setSelected(new Set());
    qc.invalidateQueries({ queryKey: ["documents", ws] });
    qc.invalidateQueries({ queryKey: ["overview", ws] });
  };
  const bulk = useMutation({
    mutationFn: (body: Parameters<typeof documentService.bulk>[1]) => documentService.bulk(ws!, body),
    onSuccess: (r, body) => {
      toast.success(body.action === "delete" ? `Deleted ${r.affected} document(s)` : `Updated ${r.affected} document(s)`);
      setBulkTag("");
      afterChange();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 20));
  const allSelected = items.length > 0 && items.every((d) => selected.has(d.id));
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const filtered = !!(q || status || tagFilter);

  return (
    <>
      <PageHeader
        title="Documents"
        description={list.data ? `${total} document${total === 1 ? "" : "s"}` : undefined}
        actions={
          canEdit && (
            <Button nativeButton={false} render={<Link href="/upload" />}>
              <Upload className="size-4" aria-hidden /> Upload
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input
            aria-label="Search documents"
            placeholder="Search title or filename"
            className="h-9 pl-8"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <NativeSelect aria-label="Filter by status" className="h-9" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase()}</option>)}
        </NativeSelect>
        <Input
          aria-label="Filter by tag"
          placeholder="Tag"
          className="h-9 w-28"
          value={tag}
          onChange={(e) => { setTag(e.target.value); setPage(1); }}
        />
        <NativeSelect aria-label="Sort" className="h-9" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
          {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </NativeSelect>
      </div>

      {canEdit && selected.size > 0 && (
        <div role="region" aria-label="Bulk actions" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border bg-accent px-3 py-2 text-sm">
          <span className="font-medium">{selected.size} selected</span>
          <Input
            aria-label="Tag to add"
            placeholder="Add tag…"
            className="h-8 w-32 bg-background"
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
          />
          <Button
            size="sm" variant="outline" disabled={!bulkTag.trim() || bulk.isPending}
            onClick={() => bulk.mutate({ action: "add_tags", ids: [...selected], tags: [bulkTag] })}
          >
            <Tag className="size-3.5" aria-hidden /> Add tag
          </Button>
          <Button size="sm" variant="destructive" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="size-3.5" aria-hidden /> Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      )}

      {list.isLoading ? (
        <div className="space-y-2">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : list.isError ? (
        <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm">
          <p className="font-medium text-destructive">Could not load documents</p>
          <p className="text-muted-foreground">{errorMessage(list.error)}</p>
          <Button size="sm" variant="outline" className="mt-3" onClick={() => list.refetch()}>Try again</Button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={filtered ? "No documents match your filters" : "No documents yet"}
          description={filtered ? "Try a different search or clear the filters." : "Upload PDF, DOCX or TXT files to get started."}
          action={!filtered && canEdit ? <Button nativeButton={false} render={<Link href="/upload" />}>Upload documents</Button> : undefined}
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                {canEdit && (
                  <TableHead className="w-10">
                    <Checkbox
                      aria-label="Select all on this page"
                      checked={allSelected}
                      onCheckedChange={(c) => setSelected(c ? new Set(items.map((d) => d.id)) : new Set())}
                    />
                  </TableHead>
                )}
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden md:table-cell">Size</TableHead>
                <TableHead className="hidden lg:table-cell">Tags</TableHead>
                <TableHead className="hidden sm:table-cell">Added</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((d) => (
                <TableRow key={d.id} data-state={selected.has(d.id) ? "selected" : undefined}>
                  {canEdit && (
                    <TableCell>
                      <Checkbox aria-label={`Select ${d.title}`} checked={selected.has(d.id)} onCheckedChange={() => toggle(d.id)} />
                    </TableCell>
                  )}
                  <TableCell className="max-w-64">
                    <Link href={`/documents/${d.id}`} className="block truncate font-medium hover:underline">{d.title}</Link>
                    <span className="block truncate text-xs text-muted-foreground">{d.filename}</span>
                  </TableCell>
                  <TableCell><StatusBadge status={d.status} /></TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">{formatBytes(d.size_bytes)}</TableCell>
                  <TableCell className="hidden lg:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {d.tags.slice(0, 3).map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
                      {d.tags.length > 3 && <span className="text-xs text-muted-foreground">+{d.tags.length - 3}</span>}
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{formatDate(d.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {total > 20 && (
        <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Page {page} of {pages}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft className="size-4" aria-hidden /> Previous
            </Button>
            <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next <ChevronRight className="size-4" aria-hidden />
            </Button>
          </div>
        </nav>
      )}

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selected.size} document(s)?</AlertDialogTitle>
            <AlertDialogDescription>
              Their extracted text and search index are removed immediately. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => bulk.mutate({ action: "delete", ids: [...selected] })}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
