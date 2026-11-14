/** Normalise for matching: lower-case, collapse whitespace, unify quotes/dashes. */
export function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

type Layout = { joined: string; ranges: [number, number][] };

function layout(texts: string[]): Layout {
  const ranges: [number, number][] = [];
  let joined = "";
  texts.forEach((t, i) => {
    const n = norm(t);
    if (i > 0) joined += " ";
    ranges.push([joined.length, joined.length + n.length]);
    joined += n;
  });
  return { joined, ranges };
}

function overlapping(ranges: [number, number][], start: number, end: number, out: Set<number>) {
  ranges.forEach(([s, e], i) => {
    if (e > s && s < end && e > start) out.add(i);
  });
}

/** Word-aligned prefixes of a passage, longest first: tolerates text-layer differences near the end. */
function candidates(needle: string): string[] {
  const n = norm(needle);
  const out = [n];
  for (const len of [160, 100, 60, 35]) {
    if (n.length > len) {
      const cut = n.lastIndexOf(" ", len);
      out.push(n.slice(0, cut > len / 2 ? cut : len));
    }
  }
  return [...new Set(out)].filter((c) => c.length >= 12);
}

/** Indices of text spans covered by the first place `passage` (or its longest matching prefix) occurs. */
export function markPassage(texts: string[], passage: string): Set<number> {
  const { joined, ranges } = layout(texts);
  const hit = new Set<number>();
  for (const c of candidates(passage)) {
    const at = joined.indexOf(c);
    if (at !== -1) {
      overlapping(ranges, at, at + c.length, hit);
      break;
    }
  }
  return hit;
}

/** Indices of spans containing any occurrence of `term`. */
export function markTerm(texts: string[], term: string): Set<number> {
  const t = norm(term);
  const hit = new Set<number>();
  if (t.length < 2) return hit;
  const { joined, ranges } = layout(texts);
  for (let at = joined.indexOf(t); at !== -1; at = joined.indexOf(t, at + t.length)) {
    overlapping(ranges, at, at + t.length, hit);
  }
  return hit;
}

export function countOccurrences(text: string, term: string): number {
  const t = norm(term);
  if (t.length < 2) return 0;
  const h = norm(text);
  let n = 0;
  for (let at = h.indexOf(t); at !== -1; at = h.indexOf(t, at + t.length)) n++;
  return n;
}

/** Split `text` into segments, flagging those that match `term` (case-insensitive, literal). */
export function splitByTerm(text: string, term: string): { text: string; match: boolean }[] {
  if (term.trim().length < 2) return [{ text, match: false }];
  const rx = new RegExp(`(${term.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  // With a capturing group, split() alternates [non-match, match, non-match, ...]: decide parity
  // BEFORE dropping empty strings.
  return text
    .split(rx)
    .map((part, i) => ({ text: part, match: i % 2 === 1 }))
    .filter((seg) => seg.text !== "");
}
