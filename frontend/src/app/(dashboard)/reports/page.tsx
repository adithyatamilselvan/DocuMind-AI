"use client";

import { useQuery } from "@tanstack/react-query";
import { FileOutput } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { analysisService } from "@/services/analysis";

export default function ReportsPage() {
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const list = useQuery({
    queryKey: ["reports", ws], queryFn: () => analysisService.reports(ws!), enabled: !!ws,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "pending" || r.status === "running") ? 2500 : false),
  });
  return (
    <>
      <PageHeader title="Reports" description="Generated reports with verified citations, downloadable as PDF or DOCX." />
      {list.isLoading ? <Skeleton className="h-32" /> : list.isError ? (
        <p role="alert" className="text-sm text-destructive">{errorMessage(list.error)}</p>
      ) : list.data?.length ? (
        <ul className="divide-y rounded-xl border bg-card text-sm">
          {list.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <Link href={`/reports/${r.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">{r.title}</Link>
              <Badge variant="outline">{r.type.replace(/_/g, " ")}</Badge>
              <Badge variant={r.status === "completed" ? "secondary" : "outline"}>{r.status}</Badge>
              <time className="text-xs text-muted-foreground" dateTime={r.created_at}>{formatDateTime(r.created_at)}</time>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState icon={FileOutput} title="No reports yet" description="Create one from a document, analysis or comparison on the Research page." />
      )}
    </>
  );
}
