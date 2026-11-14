"use client";

import { useQuery } from "@tanstack/react-query";
import { FileStack } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { documentService } from "@/services/documents";

/** Choose which documents a conversation may use. Empty selection = the whole workspace. */
export function ScopePicker({
  workspaceId, value, onChange, disabled,
}: {
  workspaceId: string;
  value: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const docs = useQuery({
    queryKey: ["scope-docs", workspaceId],
    queryFn: () => documentService.list(workspaceId, { status: "COMPLETED", page_size: 100, sort: "title", order: "asc" }),
  });
  const items = (docs.data?.items ?? []).filter((d) => d.title.toLowerCase().includes(filter.toLowerCase()));
  const label = value.length === 0 ? "All documents" : `${value.length} document${value.length === 1 ? "" : "s"}`;
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" disabled={disabled} aria-label={`Search scope: ${label}`} />}>
        <FileStack className="size-3.5" aria-hidden /> {label}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-3">
        <p className="mb-2 text-sm font-medium">Answer using</p>
        <Input aria-label="Filter documents" placeholder="Filter documents" className="mb-2 h-8" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {docs.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!docs.isLoading && items.length === 0 && <p className="py-2 text-sm text-muted-foreground">No ready documents.</p>}
          {items.map((d) => (
            <label key={d.id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted">
              <Checkbox checked={value.includes(d.id)} onCheckedChange={() => toggle(d.id)} aria-label={d.title} />
              <span className="truncate">{d.title}</span>
            </label>
          ))}
        </div>
        {value.length > 0 && (
          <Button variant="ghost" size="sm" className="mt-2 w-full" onClick={() => onChange([])}>Use all documents</Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
