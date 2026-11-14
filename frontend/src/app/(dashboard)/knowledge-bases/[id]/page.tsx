"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { StatusBadge } from "@/components/documents/status-badge";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { chatService } from "@/services/chat";
import { documentService } from "@/services/documents";
import { knowledgeService } from "@/services/knowledge";
import { atLeast } from "@/types";

export default function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canEdit = atLeast(workspace?.role, "editor");
  const kb = useQuery({
    queryKey: ["kb", ws, id], queryFn: () => knowledgeService.get(ws!, id), enabled: !!ws,
    refetchInterval: (q) => (q.state.data?.index_status === "indexing" ? 3000 : false),
  });
  const all = useQuery({ queryKey: ["scope-docs", ws], queryFn: () => documentService.list(ws!, { page_size: 100, sort: "title", order: "asc" }), enabled: !!ws && canEdit });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["kb", ws, id] }); qc.invalidateQueries({ queryKey: ["kbs", ws] }); };
  const fail = (e: unknown) => toast.error(errorMessage(e));

  const add = useMutation({ mutationFn: (docId: string) => knowledgeService.addDocuments(ws!, id, [docId]), onSuccess: refresh, onError: fail });
  const remove = useMutation({ mutationFn: (docId: string) => knowledgeService.removeDocument(ws!, id, docId), onSuccess: refresh, onError: fail });
  const reindex = useMutation({ mutationFn: () => knowledgeService.reindex(ws!, id), onSuccess: (r) => { toast.success(`Reindexing ${r.queued} document(s)`); refresh(); }, onError: fail });
  const del = useMutation({ mutationFn: () => knowledgeService.remove(ws!, id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["kbs", ws] }); router.replace("/knowledge-bases"); }, onError: fail });
  const ask = useMutation({
    mutationFn: () => chatService.create(ws!, { knowledge_base_ids: [id] }),
    onSuccess: (c) => router.push(`/assistant?c=${c.id}`),
    onError: fail,
  });

  if (kb.isLoading) return <Skeleton className="h-48" />;
  if (kb.isError || !kb.data) return <p role="alert" className="text-sm text-destructive">{errorMessage(kb.error)}</p>;
  const d = kb.data;
  const inKb = new Set(d.documents.map((x) => x.id));
  const candidates = (all.data?.items ?? []).filter((x) => !inKb.has(x.id));

  return (
    <>
      <PageHeader
        title={d.name} description={d.description || undefined}
        actions={<>
          <Button variant="outline" size="sm" disabled={ask.isPending || d.document_count === 0} onClick={() => ask.mutate()}><MessageSquare className="size-3.5" aria-hidden /> Ask this knowledge base</Button>
          {canEdit && <Button variant="outline" size="sm" disabled={reindex.isPending || d.document_count === 0} onClick={() => reindex.mutate()}><RefreshCw className="size-3.5" aria-hidden /> Reindex</Button>}
          {canEdit && <Button variant="destructive" size="sm" onClick={() => { if (confirm("Delete this knowledge base? Documents are kept.")) del.mutate(); }}><Trash2 className="size-3.5" aria-hidden /> Delete</Button>}
        </>}
      />
      <p className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">Index status: <Badge variant="outline">{d.index_status}</Badge></p>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Documents ({d.document_count})</CardTitle></CardHeader>
          <CardContent>
            {d.documents.length === 0 ? <p className="text-sm text-muted-foreground">No documents yet.</p> : (
              <ul className="divide-y text-sm">
                {d.documents.map((x) => (
                  <li key={x.id} className="flex items-center gap-2 py-2">
                    <Link href={`/documents/${x.id}`} className="min-w-0 flex-1 truncate hover:underline">{x.title}</Link>
                    <StatusBadge status={x.status as never} />
                    {canEdit && <Button variant="ghost" size="icon-xs" aria-label={`Remove ${x.title}`} onClick={() => remove.mutate(x.id)}><Trash2 className="size-3" /></Button>}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        {canEdit && (
          <Card>
            <CardHeader><CardTitle>Add documents</CardTitle></CardHeader>
            <CardContent>
              {candidates.length === 0 ? <p className="text-sm text-muted-foreground">All documents are already included.</p> : (
                <ul className="max-h-80 divide-y overflow-y-auto text-sm">
                  {candidates.map((x) => (
                    <li key={x.id} className="flex items-center gap-2 py-2">
                      <span className="min-w-0 flex-1 truncate">{x.title}</span>
                      <Button size="sm" variant="outline" disabled={add.isPending} onClick={() => add.mutate(x.id)}>Add</Button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
