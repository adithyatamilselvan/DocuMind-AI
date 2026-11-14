"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Eye, RotateCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { StatusBadge, isInProgress } from "@/components/documents/status-badge";
import { PageHeader } from "@/components/page-header";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog"; // fmt: skip
import { Badge } from "@/components/ui/badge";
import { AnchorButton, LinkButton } from "@/components/ui/link-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { Progress } from "@/components/ui/progress";
import { formatBytes, formatDateTime } from "@/lib/format";
import { documentService } from "@/services/documents";
import { uploadService } from "@/services/uploads";
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
    refetchInterval: (q) => (q.state.data && isInProgress(q.state.data.status) ? 2000 : false),
  });
  const processing = useQuery({
    queryKey: ["processing", ws, id, doc.data?.status],
    queryFn: () => uploadService.processing(ws!, id),
    enabled: !!ws && !!doc.data,
    refetchInterval: doc.data && isInProgress(doc.data.status) ? 2000 : false,
  });
  const versions = useQuery({
    queryKey: ["versions", ws, id, doc.data?.version_count],
    queryFn: () => uploadService.versions(ws!, id),
    enabled: !!ws && !!doc.data,
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const retry = useMutation({
    mutationFn: () => uploadService.retry(ws!, id),
    onSuccess: () => {
      toast.success("Processing restarted");
      qc.invalidateQueries({ queryKey: ["document", ws, id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const newVersion = useMutation({
    mutationFn: (file: File) => uploadService.uploadVersion(ws!, id, file),
    onSuccess: (r) => {
      if (r.outcome === "created") toast.success("New version uploaded");
      else toast.info(r.error ?? "Nothing to upload");
      qc.invalidateQueries({ queryKey: ["document", ws, id] });
      qc.invalidateQueries({ queryKey: ["documents", ws] });
    },
    onError: (e) => toast.error(errorMessage(e)),
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
          <>
<LinkButton variant="outline" size="sm" href={`/documents/${id}/view`}>
              <Eye className="size-3.5" aria-hidden /> View
            </LinkButton>
                        <AnchorButton variant="outline" size="sm" href={uploadService.downloadUrl(ws!, id)} download>
              <Download className="size-3.5" aria-hidden /> Download
            </AnchorButton>
            {canEdit && d.status === "FAILED" && (
              <Button variant="outline" size="sm" disabled={retry.isPending} onClick={() => retry.mutate()}>
                <RotateCw className="size-3.5" aria-hidden /> Retry processing
              </Button>
            )}
            {canEdit && (
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
            )}
          </>
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
              <dt className="text-muted-foreground">Pages</dt>
              <dd>
                {d.page_count ?? "—"}
                {d.extraction?.page_basis === "virtual" && <span className="text-xs text-muted-foreground"> (approximate, no fixed pages)</span>}
              </dd>
              {Array.isArray(d.extraction?.ocr_pages) && d.extraction.ocr_pages.length > 0 && (
                <><dt className="text-muted-foreground">OCR</dt><dd>{d.extraction.ocr_pages.length} scanned page(s)</dd></>
              )}
              {Array.isArray(d.extraction?.warnings) && d.extraction.warnings.length > 0 && (
                <><dt className="text-muted-foreground">Notes</dt><dd className="text-warning">{(d.extraction.warnings as string[]).join(" ")}</dd></>
              )}
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

        {isInProgress(d.status) && processing.data && (
          <Card className="lg:col-span-3">
            <CardHeader><CardTitle>Processing</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Progress value={Math.round(processing.data.progress * 100)} aria-label="Processing progress" />
              <p className="text-xs text-muted-foreground">
                {Object.keys(processing.data.stages).length} stage(s) finished
                {processing.data.attempts > 1 && ` · attempt ${processing.data.attempts}`}
                {processing.data.state === "retrying" && " · retrying after a temporary error"}
              </p>
            </CardContent>
          </Card>
        )}

        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Versions</CardTitle>
            {canEdit && (
              <>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".pdf,.docx,.txt"
                  className="sr-only"
                  aria-label="Upload a new version"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) newVersion.mutate(f);
                    e.target.value = "";
                  }}
                />
                <Button size="sm" variant="outline" disabled={newVersion.isPending || isInProgress(d.status)} onClick={() => fileInput.current?.click()}>
                  <Upload className="size-3.5" aria-hidden /> Upload new version
                </Button>
              </>
            )}
          </CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {versions.data?.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                  <span className="font-medium">v{v.version_no}</span>
                  {v.is_current && <Badge variant="secondary">Current</Badge>}
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{v.filename} · {formatBytes(v.size_bytes)} · {formatDateTime(v.created_at)}</span>
                  <a className="text-primary hover:underline" href={uploadService.downloadUrl(ws!, id, { version: v.id })} download>Download</a>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
