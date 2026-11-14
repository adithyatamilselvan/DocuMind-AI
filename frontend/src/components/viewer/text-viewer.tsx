"use client";

import { useEffect, useRef } from "react";

import { norm, splitByTerm } from "@/lib/highlight";
import { cn } from "@/lib/utils";
import type { DocumentText } from "@/types";

/** Renders extracted text for DOCX/TXT (which have no fixed pages) with passage + search highlights. */
export function TextViewer({
  text, page, passage, search,
}: {
  text: DocumentText;
  page: number;
  passage?: string;
  search?: string;
}) {
  const current = text.pages.find((p) => p.number === page);
  const hl = passage ? norm(passage) : "";
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    root.current?.querySelector("[data-hit]")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [page, passage, search]);

  if (!current) return <p className="text-sm text-muted-foreground">This section is empty.</p>;
  return (
    <article ref={root} className="mx-auto max-w-3xl space-y-4 rounded-md border bg-card p-6 text-sm leading-relaxed shadow-sm" data-testid="text-page">
      {current.blocks.map((b, i) => {
        const n = norm(b.text);
        const cited = hl.length >= 20 && n.length >= 20 && (hl.includes(n) || n.includes(hl.slice(0, 80)));
        const segments = splitByTerm(b.text, search ?? "");
        const body = segments.map((s, j) => (s.match ? <mark key={j} className="rounded bg-warning/50 px-0.5">{s.text}</mark> : <span key={j}>{s.text}</span>));
        const hit = cited || segments.some((s) => s.match) ? "true" : undefined;
        if (b.type === "heading")
          return <h2 key={i} data-hit={hit} className={cn("font-semibold", b.level === 1 ? "text-xl" : "text-base", cited && "rounded bg-primary/15")}>{body}</h2>;
        if (b.type === "table")
          return <pre key={i} data-hit={hit} className={cn("overflow-x-auto rounded bg-muted p-3 font-mono text-xs", cited && "ring-2 ring-primary/40")}>{b.text}</pre>;
        return <p key={i} data-hit={hit} className={cn("whitespace-pre-wrap", cited && "rounded bg-primary/15 px-1")}>{body}</p>;
      })}
    </article>
  );
}
