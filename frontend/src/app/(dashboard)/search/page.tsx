"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { splitByTerm } from "@/lib/highlight";
import { knowledgeService } from "@/services/knowledge";
import { viewerHref } from "@/lib/viewer-link";

type Mode = "hybrid" | "semantic" | "keyword";

export default function SearchPage() {
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const history = useQuery({ queryKey: ["search-history", ws], queryFn: () => knowledgeService.history(ws!), enabled: !!ws });
  const search = useMutation({
    mutationFn: (v: { q: string; m: Mode }) => knowledgeService.search(ws!, v.q, v.m),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["search-history", ws] }),
  });
  const run = (q: string, m: Mode) => { setQuery(q); setMode(m); if (q.trim()) search.mutate({ q, m }); };
  const terms = search.data?.terms ?? [];

  return (
    <>
      <PageHeader title="Search" description="Find passages across all documents: full-text, semantic or hybrid." />
      <form className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); run(query, mode); }}>
        <Input aria-label="Search query" className="min-w-60 flex-1" placeholder="Search your documents" value={query} onChange={(e) => setQuery(e.target.value)} />
        <NativeSelect aria-label="Search mode" className="h-9" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="hybrid">Hybrid</option><option value="semantic">Semantic</option><option value="keyword">Full-text</option>
        </NativeSelect>
        <Button type="submit" disabled={!query.trim() || search.isPending}>Search</Button>
      </form>

      {search.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(search.error)}</p>}
      {search.data ? (
        search.data.hits.length === 0 ? (
          <EmptyState icon={Search} title="No matching passages" description="Try different words or another search mode." />
        ) : (
          <ul className="space-y-3">
            {search.data.hits.map((h) => (
              <li key={h.chunk_id} className="rounded-lg border bg-card p-4 text-sm">
                <div className="mb-1 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  <Link href={viewerHref({ document_id: h.document_id, page_number: h.page_number ?? null, snippet: h.snippet })} className="font-medium text-foreground hover:underline">{h.document_title}</Link>
                  {h.page_number && <span>p.{h.page_number}</span>}
                  {h.section_heading && <span>· {h.section_heading}</span>}
                </div>
                <p className="line-clamp-4">
                  {splitByTerm(h.snippet, terms.join("|").replace(/\|/g, " ").split(" ")[0] ?? "").map((s, i) => (s.match ? <mark key={i} className="rounded bg-warning/50">{s.text}</mark> : <span key={i}>{s.text}</span>))}
                </p>
              </li>
            ))}
          </ul>
        )
      ) : (
        history.data && history.data.length > 0 && (
          <section aria-label="Recent searches">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-medium">Recent searches</h2>
              <Button variant="ghost" size="sm" onClick={async () => { await knowledgeService.clearHistory(ws!); qc.invalidateQueries({ queryKey: ["search-history", ws] }); }}>Clear</Button>
            </div>
            <ul className="flex flex-wrap gap-2">
              {history.data.map((h) => (
                <li key={`${h.query}-${h.mode}`}><Button variant="outline" size="sm" onClick={() => run(h.query, h.mode as Mode)}>{h.query}</Button></li>
              ))}
            </ul>
          </section>
        )
      )}
    </>
  );
}
