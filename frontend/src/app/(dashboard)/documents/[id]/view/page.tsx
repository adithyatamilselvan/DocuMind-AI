"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Info, Search, ZoomIn, ZoomOut } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { StatusBadge } from "@/components/documents/status-badge";
import { TextViewer } from "@/components/viewer/text-viewer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LinkButton } from "@/components/ui/link-button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebounced } from "@/hooks/use-debounced";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { countOccurrences } from "@/lib/highlight";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { chatService } from "@/services/chat";
import { documentService } from "@/services/documents";
import { uploadService } from "@/services/uploads";

const PdfViewer = dynamic(() => import("@/components/viewer/pdf-viewer").then((m) => m.PdfViewer), { ssr: false });
const ZOOMS = [0.6, 0.8, 1, 1.2, 1.5, 2, 2.5, 3];

function Viewer() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;

  const doc = useQuery({ queryKey: ["document", ws, id], queryFn: () => documentService.get(ws!, id), enabled: !!ws });
  const ready = doc.data?.status === "COMPLETED";
  const text = useQuery({ queryKey: ["doc-text", ws, id, doc.data?.version_count], queryFn: () => chatService.documentText(ws!, id), enabled: !!ws && ready });

  const [page, setPage] = useState(Math.max(1, Number(params.get("page")) || 1));
  const [zoomIdx, setZoomIdx] = useState(3);
  const [pdfPages, setPdfPages] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const [info, setInfo] = useState(false);
  const term = useDebounced(find, 250);
  const passage = params.get("hl") ?? undefined;

  const isPdf = doc.data?.mime_type === "application/pdf";
  const numPages = isPdf ? (pdfPages ?? doc.data?.page_count ?? 1) : (text.data?.pages.length ?? doc.data?.page_count ?? 1);
  const go = (n: number) => setPage(Math.min(Math.max(1, n), numPages));

  const matches = useMemo(
    () => (text.data && term.trim().length >= 2 ? text.data.pages.map((p) => ({ number: p.number, n: countOccurrences(p.blocks.map((b) => b.text).join(" "), term) })).filter((m) => m.n > 0) : []),
    [text.data, term],
  );
  const totalMatches = matches.reduce((a, m) => a + m.n, 0);
  const jumpToMatch = (dir: 1 | -1) => {
    if (!matches.length) return;
    const ordered = dir === 1 ? matches : [...matches].reverse();
    const next = ordered.find((m) => (dir === 1 ? m.number > page : m.number < page)) ?? ordered[0];
    setPage(next.number);
  };

  if (doc.isLoading) return <Skeleton className="h-[70svh]" />;
  if (doc.isError || !doc.data) {
    return (
      <div role="alert" className="space-y-3">
        <p className="font-medium">{errorMessage(doc.error ?? new Error("Document not found"))}</p>
        <Link href="/documents" className="text-sm text-primary hover:underline">Back to documents</Link>
      </div>
    );
  }
  const d = doc.data;

  return (
    <div className="-mx-4 -my-6 flex h-[calc(100svh-3.5rem)] flex-col sm:-mx-6 lg:-mx-8">
      <div role="toolbar" aria-label="Viewer controls" className="flex flex-wrap items-center gap-2 border-b bg-card px-3 py-2">
        <LinkButton variant="ghost" size="icon" aria-label="Back to document" href={`/documents/${id}`}><ArrowLeft className="size-4" /></LinkButton>
        <h1 className="min-w-0 max-w-64 truncate text-sm font-medium">{d.title}</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => go(page - 1)}><ChevronLeft className="size-4" /></Button>
            <label className="sr-only" htmlFor="page-input">Page number</label>
            <Input id="page-input" type="number" min={1} max={numPages} value={page} onChange={(e) => go(Number(e.target.value) || 1)} className="h-7 w-14 text-center" />
            <span className="text-sm text-muted-foreground" aria-live="polite">/ {numPages}</span>
            <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={page >= numPages} onClick={() => go(page + 1)}><ChevronRight className="size-4" /></Button>
          </div>
          {isPdf && (
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon-sm" aria-label="Zoom out" disabled={zoomIdx === 0} onClick={() => setZoomIdx((z) => z - 1)}><ZoomOut className="size-4" /></Button>
              <span className="w-10 text-center text-xs tabular-nums">{Math.round(ZOOMS[zoomIdx] * 100)}%</span>
              <Button variant="outline" size="icon-sm" aria-label="Zoom in" disabled={zoomIdx === ZOOMS.length - 1} onClick={() => setZoomIdx((z) => z + 1)}><ZoomIn className="size-4" /></Button>
            </div>
          )}
          <div className="flex items-center gap-1">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1.5 size-3.5 text-muted-foreground" aria-hidden />
              <Input aria-label="Search in document" placeholder="Find in document" className="h-7 w-40 pl-7" value={find} onChange={(e) => setFind(e.target.value)} onKeyDown={(e) => e.key === "Enter" && jumpToMatch(e.shiftKey ? -1 : 1)} />
            </div>
            {term.trim().length >= 2 && (
              <>
                <span className="text-xs text-muted-foreground" aria-live="polite">{totalMatches ? `${totalMatches} on ${matches.length} page${matches.length === 1 ? "" : "s"}` : "No matches"}</span>
                <Button variant="outline" size="icon-sm" aria-label="Previous match" disabled={!matches.length} onClick={() => jumpToMatch(-1)}><ChevronLeft className="size-4" /></Button>
                <Button variant="outline" size="icon-sm" aria-label="Next match" disabled={!matches.length} onClick={() => jumpToMatch(1)}><ChevronRight className="size-4" /></Button>
              </>
            )}
          </div>
          <Button variant={info ? "secondary" : "outline"} size="icon-sm" aria-label="Document information" aria-pressed={info} onClick={() => setInfo((v) => !v)}><Info className="size-4" /></Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-auto bg-muted/40 p-4">
          {!ready ? (
            <p role="status" className="py-10 text-center text-sm text-muted-foreground">This document is not ready yet (<StatusBadge status={d.status} />).</p>
          ) : error ? (
            <p role="alert" className="py-10 text-center text-sm text-destructive">{error}</p>
          ) : isPdf ? (
            <PdfViewer url={uploadService.downloadUrl(ws!, id, { inline: true })} page={page} scale={ZOOMS[zoomIdx]} passage={passage} search={term} onLoaded={setPdfPages} onError={setError} />
          ) : text.data ? (
            <>
              {text.data.page_basis === "virtual" && <p className="mx-auto mb-3 max-w-3xl text-xs text-muted-foreground">This format has no fixed pages: sections are approximate groupings.</p>}
              <TextViewer text={text.data} page={page} passage={passage} search={term} />
            </>
          ) : text.isError ? (
            <p role="alert" className="py-10 text-center text-sm text-destructive">{errorMessage(text.error)}</p>
          ) : (
            <Skeleton className="mx-auto h-96 max-w-3xl" />
          )}
        </div>
        {info && (
          <aside aria-label="Document information" className={cn("w-72 shrink-0 overflow-y-auto border-l bg-card p-4 text-sm", "max-md:absolute max-md:inset-y-0 max-md:right-0 max-md:z-20 max-md:shadow-xl")}>
            <h2 className="mb-3 font-semibold">Information</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2">
              <dt className="text-muted-foreground">File</dt><dd className="break-all">{d.filename}</dd>
              <dt className="text-muted-foreground">Size</dt><dd>{formatBytes(d.size_bytes)}</dd>
              <dt className="text-muted-foreground">Pages</dt><dd>{d.page_count ?? "—"}</dd>
              <dt className="text-muted-foreground">Language</dt><dd>{d.language ?? "—"}</dd>
              <dt className="text-muted-foreground">Category</dt><dd>{d.category ?? "—"}</dd>
            </dl>
          </aside>
        )}
      </div>
    </div>
  );
}

export default function ViewerPage() {
  return <Suspense><Viewer /></Suspense>;
}
