"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace, useMe } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import { documentService } from "@/services/documents";

function humanizeAction(a: string): string {
  const map: Record<string, string> = {
    "auth.register": "created their account",
    "auth.login": "signed in",
    "auth.logout": "signed out",
    "workspace.create": "created a workspace",
    "workspace.update": "updated workspace settings",
    "member.add": "added a member",
    "member.role": "changed a member's role",
    "member.remove": "removed a member",
    "document.delete": "deleted a document",
  };
  if (map[a]) return map[a];
  if (a.startsWith("document.bulk.")) return `ran bulk action "${a.slice(14).replace(/_/g, " ")}"`;
  return a.replace(/[._]/g, " ");
}

function Kpi({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  );
}

export default function DashboardPage() {
  const { data: user } = useMe();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const overview = useQuery({
    queryKey: ["overview", ws],
    queryFn: () => documentService.overview(ws!),
    enabled: !!ws,
    refetchInterval: 15_000,
  });
  const o = overview.data;

  return (
    <>
      <PageHeader
        title={`Welcome${user ? `, ${user.name.split(" ")[0]}` : ""}`}
        description={workspace ? `Overview of ${workspace.name}` : undefined}
      />
      {overview.isError ? (
        <p role="alert" className="text-sm text-destructive">{errorMessage(overview.error)}</p>
      ) : !o ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Documents" value={formatNumber(o.total_documents)} />
            <Kpi label="Processed" value={formatNumber(o.completed_documents)} hint={`Success rate ${formatPercent(o.processing_success_rate)}`} />
            <Kpi label="In progress" value={formatNumber(o.in_progress_documents)} hint={`${formatNumber(o.failed_documents)} failed`} />
            <Kpi label="Storage" value={formatBytes(o.storage_bytes)} />
            <Kpi label="Knowledge bases" value={formatNumber(o.knowledge_bases)} />
            <Kpi label="Conversations" value={formatNumber(o.conversations)} />
            <Kpi label="AI requests (30d)" value={formatNumber(o.ai_requests_30d)} />
            <Kpi label="AI tokens (30d)" value={formatNumber(o.ai_tokens_30d)} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>AI usage, last 30 days</CardTitle>
                <CardDescription>Requests per day, from recorded usage.</CardDescription>
              </CardHeader>
              <CardContent>
                {o.ai_requests_30d === 0 ? (
                  <p className="py-10 text-center text-sm text-muted-foreground">No AI usage recorded yet.</p>
                ) : (
                  <div className="h-56" role="img" aria-label="Bar chart of AI requests per day for the last 30 days">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={o.usage_trend}>
                        <CartesianGrid vertical={false} stroke="var(--border)" />
                        <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} interval={4} />
                        <YAxis allowDecimals={false} width={32} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
                        <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                        <Bar dataKey="requests" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Categories</CardTitle></CardHeader>
              <CardContent>
                {o.categories.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No documents yet.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {o.categories.map((c) => (
                      <li key={c.label} className="flex items-center justify-between gap-3">
                        <span className="truncate">{c.label}</span>
                        <span className="tabular-nums text-muted-foreground">{c.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Frequently opened</CardTitle></CardHeader>
              <CardContent>
                {o.top_documents.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Documents you open will show up here.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {o.top_documents.map((d) => (
                      <li key={d.id} className="flex items-center justify-between gap-3">
                        <Link href={`/documents/${d.id}`} className="truncate hover:underline">{d.title}</Link>
                        <span className="tabular-nums text-muted-foreground">{d.access_count}×</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
              <CardContent>
                {o.recent_activity.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No activity yet.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {o.recent_activity.map((a, i) => (
                      <li key={i} className="flex flex-wrap items-baseline justify-between gap-x-3">
                        <span><span className="font-medium">{a.actor_name ?? "Someone"}</span> {humanizeAction(a.action)}</span>
                        <time className="text-xs text-muted-foreground" dateTime={a.created_at}>{formatDateTime(a.created_at)}</time>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
