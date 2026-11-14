import type { Citation } from "@/types";

/** Deep link into the document viewer for a cited passage. `hl` is the passage to highlight. */
export function viewerHref(c: Pick<Citation, "document_id" | "page_number" | "snippet">): string {
  const p = new URLSearchParams();
  if (c.page_number) p.set("page", String(c.page_number));
  p.set("hl", c.snippet.slice(0, 400));
  return `/documents/${c.document_id}/view?${p.toString()}`;
}
