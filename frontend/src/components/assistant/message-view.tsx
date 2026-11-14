"use client";

import { AlertTriangle, Check, Copy, RefreshCw, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ChatMessage, Citation } from "@/types";

import { RichText } from "./rich-text";

export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground">{text}</div>
    </div>
  );
}

export function AssistantMessage({
  message, streamingText, status, error, isLast, onCite, onRegenerate, onFeedback, onRetry,
}: {
  message?: ChatMessage;
  streamingText?: string;
  status?: string;
  error?: string;
  isLast?: boolean;
  onCite: (citations: Citation[], index: number) => void;
  onRegenerate?: () => void;
  onFeedback?: (rating: "up" | "down" | null) => void;
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const streaming = streamingText !== undefined;
  const citations = message?.citations ?? [];
  // During streaming the model still writes provisional [S1] labels; hide them until validated.
  const text = streaming ? streamingText.replace(/\s*\[S\d+(?:\s*[,;]?\s*S\d+)*\]/g, "") : (message?.content ?? "");

  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Sparkles className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1" aria-live={streaming ? "polite" : undefined} aria-busy={streaming}>
        {streaming && !text && (
          <p className="text-sm text-muted-foreground">
            {status === "searching" ? "Searching your documents…" : status === "answering" ? "Writing the answer…" : "Understanding the question…"}
          </p>
        )}
        {text && (
          <RichText text={text} citedIndexes={new Set(citations.map((c) => c.index))} onCite={(i) => onCite(citations, i)} />
        )}
        {error && (
          <div role="alert" className="mt-2 flex items-center gap-2 rounded-md border border-destructive/40 p-3 text-sm">
            <AlertTriangle className="size-4 shrink-0 text-destructive" aria-hidden />
            <span className="flex-1">{error}</span>
            {onRetry && <Button size="sm" variant="outline" onClick={onRetry}>Try again</Button>}
          </div>
        )}
        {message?.insufficient_evidence && (
          <p className="mt-2 text-xs text-muted-foreground">No supporting passages were found, so no citations are shown.</p>
        )}
        {message && (message.warnings ?? []).length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs text-warning">
            {(message.warnings ?? []).map((w) => <li key={w}>⚠ {w}</li>)}
          </ul>
        )}
        {citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Sources">
            {citations.map((c) => (
              <button
                key={c.index}
                type="button"
                onClick={() => onCite(citations, c.index)}
                className="inline-flex max-w-56 items-center gap-1.5 rounded-md border bg-card px-2 py-1 text-xs hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <span className="font-semibold text-primary">{c.index}</span>
                <span className="truncate">{c.document_title}{c.page_number ? ` · p.${c.page_number}` : ""}</span>
              </button>
            ))}
          </div>
        )}
        {message && !streaming && (
          <div className="mt-2 flex items-center gap-0.5 text-muted-foreground">
            <Button variant="ghost" size="icon-sm" aria-label="Copy answer" onClick={async () => {
              await navigator.clipboard.writeText(message.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}>
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </Button>
            {isLast && onRegenerate && (
              <Button variant="ghost" size="icon-sm" aria-label="Regenerate answer" onClick={onRegenerate}><RefreshCw className="size-3.5" /></Button>
            )}
            <Button variant="ghost" size="icon-sm" aria-label="Good answer" aria-pressed={message.feedback === "up"} className={cn(message.feedback === "up" && "text-success")} onClick={() => onFeedback?.(message.feedback === "up" ? null : "up")}>
              <ThumbsUp className="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label="Poor answer" aria-pressed={message.feedback === "down"} className={cn(message.feedback === "down" && "text-destructive")} onClick={() => onFeedback?.(message.feedback === "down" ? null : "down")}>
              <ThumbsDown className="size-3.5" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
