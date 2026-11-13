"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { StatusBadge } from "@/components/documents/status-badge";
import { PageHeader } from "@/components/page-header";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"; // fmt: skip
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import { documentService } from "@/services/documents";
import { atLeast } from "@/types";

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canEdit = atLeast(workspace?.role, "editor");

  const doc = useQuery({
    queryKey: ["document", ws, id],
    queryFn: () => documentService.get(ws!, id),
    enabled: !!ws,
  });
  const collections = useQuery({
    queryKey: ["collections", ws],
    queryFn: () => documentService.collections(ws!),
    enabled: !!ws,
  });

  const [title, setTitle] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [tags, setTags] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Parameters<typeof documentService.update>[2]) => documentService.update(ws!, id, body),
    onSuccess: () => {
      toast.success("Saved");
      setTitle(null); setCategory(null); setTags(null);
      qc.invalidateQueries({ queryKey: ["document", ws, id] });
      qc.invalidateQueries({ queryKey: ["documents", ws] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => documentService.remove(ws!, id),
    onSuccess: () => {
      toast.success("Document deleted");
      qc.invalidateQueries({ queryKey: ["documents", ws] });
      router.replace("/documents");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (doc.isLoading) return <Skeleton className="h-64" />;
  if (doc.isError || !doc.data)
    return (
      <div role="alert" className="space-y-3">
        <p className="font-medium">{errorMessage(doc.error ?? new Error("Document not found"))}</p>
        <Link href="/documents" className="text-sm text-primary hover:underline">Back to documents</Link>
      </div>
    );
  const d = doc.data;
  const memberOf = new Set(d.collection_ids);

  return (
    <>
      <Link href="/documents" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Documents
      </Link>
      <PageHeader
        title={d.title}
        description={d.filename}
        actions={
          canEdit && (
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="destructive" size="sm" />}>
                <Trash2 className="size-3.5" aria-hidden /> Delete
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete this document?</AlertDialogTitle>
                  <AlertDialogDescription>Its extracted text and search index are removed immediately.</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => remove.mutate()}>Delete</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate({
                  ...(title !== null && { title }),
                  ...(category !== null && { category: category || null }),
                  ...(tags !== null && { tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }),
                });
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="title">Title</Label>
                <Input id="title" disabled={!canEdit} value={title ?? d.title} onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="category">Category</Label>
                <Input id="category" disabled={!canEdit} value={category ?? d.category ?? ""} onChange={(e) => setCategory(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tags">Tags (comma separated)</Label>
                <Input id="tags" disabled={!canEdit} value={tags ?? d.tags.join(", ")} onChange={(e) => setTags(e.target.value)} />
              </div>
              {canEdit && (
                <Button type="submit" disabled={save.isPending || (title === null && category === null && tags === null)}>
                  Save changes
                </Button>
              )}
            </form>

            {collections.data && collections.data.length > 0 && (
              <fieldset className="mt-6">
                <legend className="mb-2 text-sm font-medium">Collections</legend>
                <div className="flex flex-wrap gap-2">
                  {collections.data.map((c) => (
                    <Button
                      key={c.id}
                      type="button"
                      size="sm"
                      disabled={!canEdit || save.isPending}
                      variant={memberOf.has(c.id) ? "default" : "outline"}
                      aria-pressed={memberOf.has(c.id)}
                      onClick={() =>
                        save.mutate({
                          collection_ids: memberOf.has(c.id)
                            ? d.collection_ids.filter((x) => x !== c.id)
                            : [...d.collection_ids, c.id],
                        })
                      }
                    >
                      {c.name}
                    </Button>
                  ))}
                </div>
              </fieldset>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Information</CardTitle></CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Status</dt><dd><StatusBadge status={d.status} /></dd>
              {d.error && (<><dt className="text-muted-foreground">Error</dt><dd className="text-destructive">{d.error}</dd></>)}
              <dt className="text-muted-foreground">Type</dt><dd className="break-all">{d.mime_type}</dd>
              <dt className="text-muted-foreground">Size</dt><dd>{formatBytes(d.size_bytes)}</dd>
              <dt className="text-muted-foreground">Pages</dt><dd>{d.page_count ?? "—"}</dd>
              <dt className="text-muted-foreground">Language</dt><dd>{d.language ?? "—"}</dd>
              <dt className="text-muted-foreground">Versions</dt><dd>{d.version_count}</dd>
              <dt className="text-muted-foreground">Added</dt><dd>{formatDateTime(d.created_at)}</dd>
              <dt className="text-muted-foreground">SHA-256</dt><dd className="break-all font-mono text-xs">{d.sha256}</dd>
            </dl>
            {d.tags.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1">{d.tags.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</div>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
