"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { analysisService } from "@/services/analysis";
import { documentService } from "@/services/documents";
import { atLeast } from "@/types";

const running = (s: string) => s === "pending" || s === "running";

export default function AnalysisHub() {
  const qc = useQueryClient();
  const router = useRouter();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canEdit = atLeast(workspace?.role, "editor");
  const [sel, setSel] = useState<string[]>([]);
  const docs = useQuery({ queryKey: ["scope-docs", ws], queryFn: () => documentService.list(ws!, { status: "COMPLETED", page_size: 100, sort: "title", order: "asc" }), enabled: !!ws });
  const papers = useQuery({
    queryKey: ["research", ws], queryFn: () => analysisService.papers(ws!), enabled: !!ws,
    refetchInterval: (q) => (q.state.data?.some((x) => running(x.status)) ? 2500 : false),
  });
  const comps = useQuery({
    queryKey: ["comparisons", ws], queryFn: () => analysisService.comparisons(ws!), enabled: !!ws,
    refetchInterval: (q) => (q.state.data?.some((x) => running(x.status)) ? 2500 : false),
  });
  const fail = (e: unknown) => toast.error(errorMessage(e));
  const refresh = () => { qc.invalidateQueries({ queryKey: ["research", ws] }); qc.invalidateQueries({ queryKey: ["comparisons", ws] }); };
  const paper = useMutation({ mutationFn: () => analysisService.analysePaper(ws!, sel[0]), onSuccess: refresh, onError: fail });
  const synth = useMutation({ mutationFn: () => analysisService.synthesise(ws!, sel), onSuccess: refresh, onError: fail });
  const compare = useMutation({ mutationFn: () => analysisService.compare(ws!, sel), onSuccess: refresh, onError: fail });
  const versions = useMutation({ mutationFn: () => analysisService.compareVersions(ws!, sel[0]), onSuccess: refresh, onError: fail });
  const report = useMutation({
    mutationFn: (v: { type: "research" | "literature_review" | "comparison"; id: string }) =>
      analysisService.createReport(ws!, v.type === "comparison" ? { type: v.type, comparison_id: v.id } : { type: v.type, analysis_id: v.id }),
    onSuccess: (r) => router.push(`/reports/${r.id}`), onError: fail,
  });
  const reportFromDocs = useMutation({
    mutationFn: (type: "document_summary" | "multi_document") => analysisService.createReport(ws!, { type, document_ids: sel }),
    onSuccess: (r) => router.push(`/reports/${r.id}`), onError: fail,
  });
  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <>
      <PageHeader title="Research and comparison" description="Analyse papers, write literature reviews, compare documents or versions, and export reports." />
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>1. Choose documents</CardTitle>
          <CardDescription>{sel.length} selected. Only processed documents are listed.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="mb-4 max-h-56 divide-y overflow-y-auto text-sm">
            {(docs.data?.items ?? []).map((d) => (
              <li key={d.id}>
                <label className="flex cursor-pointer items-center gap-2 py-1.5">
                  <Checkbox checked={sel.includes(d.id)} onCheckedChange={() => toggle(d.id)} aria-label={d.title} />
                  <span className="truncate">{d.title}</span>
                  <span className="text-xs text-muted-foreground">v{d.version_count}</span>
                </label>
              </li>
            ))}
            {docs.data?.items.length === 0 && <li className="py-2 text-muted-foreground">No processed documents yet.</li>}
          </ul>
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={sel.length !== 1 || paper.isPending} onClick={() => paper.mutate()}>Analyse paper</Button>
              <Button size="sm" disabled={sel.length < 2 || synth.isPending} onClick={() => synth.mutate()}>Literature review</Button>
              <Button size="sm" disabled={sel.length < 2 || compare.isPending} onClick={() => compare.mutate()}>Compare documents</Button>
              <Button size="sm" variant="outline" disabled={sel.length !== 1 || versions.isPending} onClick={() => versions.mutate()}>Compare versions</Button>
              <Button size="sm" variant="outline" disabled={sel.length !== 1 || reportFromDocs.isPending} onClick={() => reportFromDocs.mutate("document_summary")}>Summary report</Button>
              <Button size="sm" variant="outline" disabled={sel.length < 2 || reportFromDocs.isPending} onClick={() => reportFromDocs.mutate("multi_document")}>Multi-document report</Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Research analyses</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {(papers.data ?? []).map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2 py-2">
                  <span className="min-w-0 flex-1 truncate">{a.title}</span>
                  <Badge variant="outline">{a.kind === "paper" ? "paper" : "review"}</Badge>
                  <Badge variant={a.status === "completed" ? "secondary" : "outline"} title={a.error ?? undefined}>{a.status}</Badge>
                  {a.status === "completed" && canEdit && <Button size="xs" variant="outline" onClick={() => report.mutate({ type: a.kind === "paper" ? "research" : "literature_review", id: a.id })}>Report</Button>}
                  <time className="w-full text-xs text-muted-foreground" dateTime={a.created_at}>{formatDateTime(a.created_at)}{a.error ? ` · ${a.error}` : ""}</time>
                </li>
              ))}
              {papers.data?.length === 0 && <li className="py-2 text-muted-foreground">None yet.</li>}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Comparisons</CardTitle></CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {(comps.data ?? []).map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-2 py-2">
                  <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  <Badge variant="outline">{c.kind}</Badge>
                  <Badge variant={c.status === "completed" ? "secondary" : "outline"} title={c.error ?? undefined}>{c.status}</Badge>
                  {c.status === "completed" && canEdit && <Button size="xs" variant="outline" onClick={() => report.mutate({ type: "comparison", id: c.id })}>Report</Button>}
                  <time className="w-full text-xs text-muted-foreground" dateTime={c.created_at}>{formatDateTime(c.created_at)}{c.error ? ` · ${c.error}` : ""}</time>
                </li>
              ))}
              {comps.data?.length === 0 && <li className="py-2 text-muted-foreground">None yet.</li>}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
