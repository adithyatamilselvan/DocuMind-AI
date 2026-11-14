"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { insightsService } from "@/services/insights";

export default function InsightsOverviewPage() {
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const [category, setCategory] = useState("");
  const all = useQuery({ queryKey: ["insights-list", ws], queryFn: () => insightsService.list(ws!), enabled: !!ws });
  const categories = useMemo(() => [...new Set((all.data ?? []).map((i) => i.category).filter((c): c is string => !!c))].sort(), [all.data]);
  const items = (all.data ?? []).filter((i) => !category || i.category === category);

  return (
    <>
      <PageHeader
        title="Document intelligence"
        description="AI-generated summaries and classification across your documents."
        actions={categories.length > 0 && (
          <NativeSelect aria-label="Filter by category" className="h-9" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </NativeSelect>
        )}
      />
      {all.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : all.isError ? (
        <p role="alert" className="text-sm text-destructive">{errorMessage(all.error)}</p>
      ) : items.length === 0 ? (
        <EmptyState icon={Sparkles} title="No insights yet" description="Insights appear here after documents finish processing and the AI analysis completes." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.map((i) => (
            <Card key={i.document_id}>
              <CardHeader>
                <CardTitle className="text-base"><Link href={`/documents/${i.document_id}`} className="hover:underline">{i.title}</Link></CardTitle>
                <CardDescription className="flex items-center gap-2">
                  {i.category && <Badge variant="outline">{i.category}</Badge>}
                  {i.document_type} · {formatDate(i.generated_at)}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="line-clamp-4">{i.summary}</p>
                <div className="flex flex-wrap gap-1">{i.topics.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
