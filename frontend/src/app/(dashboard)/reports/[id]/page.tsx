"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { AnchorButton } from "@/components/ui/link-button";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { viewerHref } from "@/lib/viewer-link";
import { analysisService } from "@/services/analysis";
import { atLeast } from "@/types";

type Section = { title: string; paragraphs: string[]; bullets: { text: string; refs: number[] }[]; table: { columns: string[]; rows: string[][] } | null };
type Ref = { n: number; document_id: string | null; document_title: string; page: number | null; quote: string | null };

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const q = useQuery({
    queryKey: ["report", ws, id], queryFn: () => analysisService.report(ws!, id), enabled: !!ws,
    refetchInterval: (query) => (["pending", "running"].includes(query.state.data?.status ?? "") ? 2000 : false),
  });
  const del = useMutation({
    mutationFn: () => analysisService.deleteReport(ws!, id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["reports", ws] }); router.replace("/reports"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (q.isLoading) return <Skeleton className="h-64" />;
  if (q.isError || !q.data) return <p role="alert" className="text-sm text-destructive">{errorMessage(q.error)}</p>;
  const r = q.data;
  const sections = (r.sections ?? []) as unknown as Section[];
  const refs = (r.references ?? []) as unknown as Ref[];

  return (
    <>
      <PageHeader
        title={r.title}
        description={`${r.type.replace(/_/g, " ")} · ${r.status}`}
        actions={r.status === "completed" && ws ? (
          <>
            <AnchorButton variant="outline" size="sm" href={analysisService.downloadUrl(ws, id, "pdf")} download><Download className="size-3.5" aria-hidden /> PDF</AnchorButton>
            <AnchorButton variant="outline" size="sm" href={analysisService.downloadUrl(ws, id, "docx")} download><Download className="size-3.5" aria-hidden /> DOCX</AnchorButton>
            {atLeast(workspace?.role, "editor") && <Button variant="destructive" size="sm" onClick={() => { if (confirm("Delete this report?")) del.mutate(); }}><Trash2 className="size-3.5" aria-hidden /> Delete</Button>}
          </>
        ) : undefined}
      />
      {r.status === "failed" && <p role="alert" className="text-sm text-destructive">Report failed: {r.error}</p>}
      {(r.status === "pending" || r.status === "running") && <p role="status" className="text-sm text-muted-foreground">Generating report…</p>}
      {r.status === "completed" && (
        <article className="mx-auto max-w-3xl space-y-6 rounded-xl border bg-card p-6 text-sm">
          {sections.map((s, i) => (
            <section key={i}>
              <h2 className="mb-2 text-base font-semibold">{s.title}</h2>
              {s.paragraphs.map((p, j) => <p key={j} className="mb-2 whitespace-pre-wrap">{p}</p>)}
              {s.bullets.length > 0 && (
                <ul className="list-disc space-y-1 pl-5">
                  {s.bullets.map((b, j) => <li key={j}>{b.text}{b.refs.map((n) => <sup key={n} className="ml-0.5 text-primary">[{n}]</sup>)}</li>)}
                </ul>
              )}
              {s.table && (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-xs">
                    <thead><tr>{s.table.columns.map((c) => <th key={c} className="border bg-muted px-2 py-1 text-left">{c}</th>)}</tr></thead>
                    <tbody>{s.table.rows.map((row, k) => <tr key={k}>{row.map((v, m) => <td key={m} className="border px-2 py-1 align-top">{v}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              )}
            </section>
          ))}
          {refs.length > 0 && (
            <section>
              <h2 className="mb-2 text-base font-semibold">References</h2>
              <ol className="space-y-1 text-xs text-muted-foreground">
                {refs.map((x) => (
                  <li key={x.n} id={`ref-${x.n}`}>
                    [{x.n}]{" "}
                    {x.document_id ? <Link className="hover:underline" href={viewerHref({ document_id: x.document_id, page_number: x.page, snippet: x.quote ?? "" })}>{x.document_title}{x.page ? `, page ${x.page}` : ""}</Link> : x.document_title}
                    {x.quote && <> — “{x.quote}”</>}
                  </li>
                ))}
              </ol>
            </section>
          )}
        </article>
      )}
    </>
  );
}
