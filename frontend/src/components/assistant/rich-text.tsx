import { Fragment, type ReactNode } from "react";

export type Block =
  | { type: "p"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] };

/** Minimal block parser for model answers: paragraphs and bullet/numbered lists. */
export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of text.split(/\n\s*\n/)) {
    const lines = chunk.split("\n").filter((l) => l.trim());
    if (!lines.length) continue;
    const bullet = lines.every((l) => /^\s*[-*•]\s+/.test(l));
    const numbered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l));
    if (bullet) blocks.push({ type: "ul", items: lines.map((l) => l.replace(/^\s*[-*•]\s+/, "")) });
    else if (numbered) blocks.push({ type: "ol", items: lines.map((l) => l.replace(/^\s*\d+[.)]\s+/, "")) });
    else blocks.push({ type: "p", text: lines.join("\n") });
  }
  return blocks;
}

export type Inline =
  | { type: "text"; text: string }
  | { type: "bold"; text: string }
  | { type: "code"; text: string }
  | { type: "cite"; index: number };

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  for (const part of text.split(TOKEN)) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) out.push({ type: "bold", text: part.slice(2, -2) });
    else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) out.push({ type: "code", text: part.slice(1, -1) });
    else if (/^\[\d+\]$/.test(part)) out.push({ type: "cite", index: Number(part.slice(1, -1)) });
    else out.push({ type: "text", text: part });
  }
  return out;
}

export function RichText({
  text,
  citedIndexes,
  onCite,
}: {
  text: string;
  /** Only [n] markers that match a real citation are rendered as interactive chips. */
  citedIndexes: Set<number>;
  onCite: (index: number) => void;
}) {
  const inline = (s: string): ReactNode =>
    parseInline(s).map((n, i) => {
      switch (n.type) {
        case "bold":
          return <strong key={i}>{n.text}</strong>;
        case "code":
          return <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{n.text}</code>;
        case "cite":
          return citedIndexes.has(n.index) ? (
            <button
              key={i}
              type="button"
              onClick={() => onCite(n.index)}
              aria-label={`Open source ${n.index}`}
              className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded bg-primary/15 px-1 align-baseline text-[0.7rem] font-semibold text-primary hover:bg-primary/25 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              {n.index}
            </button>
          ) : (
            <Fragment key={i}>{`[${n.index}]`}</Fragment>
          );
        default:
          return <Fragment key={i}>{n.text}</Fragment>;
      }
    });

  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {parseBlocks(text).map((b, i) =>
        b.type === "p" ? (
          <p key={i} className="whitespace-pre-wrap">{inline(b.text)}</p>
        ) : b.type === "ul" ? (
          <ul key={i} className="list-disc space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>
        ) : (
          <ol key={i} className="list-decimal space-y-1 pl-5">{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ol>
        ),
      )}
    </div>
  );
}
