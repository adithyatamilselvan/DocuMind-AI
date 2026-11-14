"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { LinkButton } from "@/components/ui/link-button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { viewerHref } from "@/lib/viewer-link";
import { cn } from "@/lib/utils";
import type { Citation } from "@/types";

export function SourcePanel({
  citations, selected, open, onOpenChange,
}: {
  citations: Citation[];
  selected: number | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const refs = useRef<Record<number, HTMLLIElement | null>>({});
  useEffect(() => {
    if (open && selected) refs.current[selected]?.scrollIntoView({ block: "nearest" });
  }, [open, selected]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Sources</SheetTitle>
          <SheetDescription>Passages this answer is based on. Page numbers come from the document, not the model.</SheetDescription>
        </SheetHeader>
        <ul className="space-y-3 px-4 pb-6">
          {citations.map((c) => (
            <li
              key={c.index}
              ref={(el) => { refs.current[c.index] = el; }}
              className={cn("rounded-lg border p-3 text-sm", c.index === selected && "border-primary ring-2 ring-primary/20")}
            >
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{c.index}</Badge>
                <span className="font-medium">{c.document_title}</span>
              </div>
              <p className="mb-2 text-xs text-muted-foreground">
                {c.page_number ? (c.page_is_exact ? `Page ${c.page_number}` : `Section ${c.page_number} (approximate)`) : "Page unknown"}
                {c.section_heading && ` · ${c.section_heading}`}
              </p>
              <blockquote className="border-l-2 pl-3 text-muted-foreground">{c.snippet}</blockquote>
              <LinkButton variant="link" size="sm" className="mt-1 h-auto p-0" href={viewerHref(c)}>
                Open in document <ExternalLink className="size-3" aria-hidden />
              </LinkButton>
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  );
}
