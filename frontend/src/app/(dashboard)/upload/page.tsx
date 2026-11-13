"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, CopyCheck, FileUp, Loader2, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { uploadService } from "@/services/uploads";
import { atLeast } from "@/types";

type Item = {
  id: string;
  file: File;
  state: "pending" | "uploading" | "created" | "duplicate" | "rejected" | "error";
  progress: number;
  message?: string;
  documentId?: string;
};

const CONCURRENCY = 2;
let counter = 0;

export default function UploadPage() {
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canUpload = atLeast(workspace?.role, "editor");
  const config = useQuery({ queryKey: ["client-config"], queryFn: uploadService.config, staleTime: Infinity });
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const abort = useRef(new AbortController());

  const consentMissing =
    !!config.data?.external_ai_processing && workspace?.settings?.ai_processing_consent !== true;
  const patch = useCallback(
    (id: string, p: Partial<Item>) => setItems((cur) => cur.map((i) => (i.id === id ? { ...i, ...p } : i))),
    [],
  );

  async function runUploads(batch: Item[]) {
    const queue = [...batch];
    const worker = async () => {
      for (let item = queue.shift(); item; item = queue.shift()) {
        patch(item.id, { state: "uploading" });
        try {
          const r = await uploadService.uploadOne(ws!, item.file, (f) => patch(item.id, { progress: f }), abort.current.signal);
          if (r.outcome === "created") patch(item.id, { state: "created", progress: 1, documentId: r.document?.id });
          else if (r.outcome === "duplicate")
            patch(item.id, { state: "duplicate", progress: 1, message: r.error ?? "Already uploaded", documentId: r.existing_document_id ?? undefined });
          else patch(item.id, { state: "rejected", message: r.error ?? "Rejected" });
        } catch (e) {
          patch(item.id, { state: "error", message: errorMessage(e) });
        }
      }
    };
    await Promise.all(Array.from({ length: CONCURRENCY }, worker));
    qc.invalidateQueries({ queryKey: ["documents", ws] });
    qc.invalidateQueries({ queryKey: ["overview", ws] });
  }

  function addFiles(list: FileList | File[]) {
    if (!config.data || !ws) return;
    const max = config.data.max_upload_mb * 1024 * 1024;
    const files = Array.from(list);
    const batch: Item[] = files.map((file) => {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      const base = { id: `f${++counter}`, file, progress: 0 };
      if (!config.data!.allowed_extensions.includes(ext))
        return { ...base, state: "rejected", message: "Only PDF, DOCX and TXT files are supported" } as Item;
      if (file.size > max)
        return { ...base, state: "rejected", message: `Larger than the ${config.data!.max_upload_mb} MB limit` } as Item;
      if (file.size === 0) return { ...base, state: "rejected", message: "The file is empty" } as Item;
      return { ...base, state: "pending" } as Item;
    });
    setItems((cur) => [...batch, ...cur]);
    void runUploads(batch.filter((i) => i.state === "pending"));
  }

  const disabled = !canUpload || consentMissing || !config.data;
  const done = items.filter((i) => i.state === "created").length;

  return (
    <>
      <PageHeader title="Upload" description="Add PDF, DOCX or TXT documents to this workspace." />

      {consentMissing && (
        <div role="alert" className="mb-4 flex gap-3 rounded-lg border border-warning/50 bg-warning/10 p-4 text-sm">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div>
            <p className="font-medium">External AI processing is not enabled for this workspace</p>
            <p className="text-muted-foreground">
              Documents are embedded and analysed by a third-party AI provider. {atLeast(workspace?.role, "admin") ? (
                <>Enable it in <Link href="/settings" className="font-medium underline">Settings</Link> to upload.</>
              ) : "Ask a workspace admin to enable it in Settings."}
            </p>
          </div>
        </div>
      )}
      {!canUpload && <p className="mb-4 text-sm text-muted-foreground">You have view-only access to this workspace.</p>}

      <div
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          dragging ? "border-primary bg-accent" : "border-border",
          disabled && "opacity-60",
        )}
      >
        <FileUp className="size-8 text-muted-foreground" aria-hidden />
        <p className="font-medium">Drag and drop files here</p>
        <p className="text-sm text-muted-foreground">
          PDF, DOCX or TXT, up to {config.data?.max_upload_mb ?? "…"} MB each, {config.data?.max_files_per_upload ?? "…"} files at a time
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt"
          className="sr-only"
          aria-label="Choose files to upload"
          disabled={disabled}
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <Button disabled={disabled} onClick={() => inputRef.current?.click()}>Browse files</Button>
      </div>

      {items.length > 0 && (
        <section aria-label="Uploads" className="mt-6">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-medium">{done} of {items.length} uploaded</h2>
            <Button variant="ghost" size="sm" onClick={() => setItems((c) => c.filter((i) => i.state === "uploading" || i.state === "pending"))}>
              Clear finished
            </Button>
          </div>
          <ul className="divide-y rounded-xl border bg-card">
            {items.map((i) => (
              <li key={i.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <StateIcon state={i.state} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{i.file.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatBytes(i.file.size)}
                    {i.state === "created" && " · uploaded, processing will continue in the background"}
                    {i.message && ` · ${i.message}`}
                  </p>
                  {i.state === "uploading" && <Progress value={Math.round(i.progress * 100)} className="mt-2" aria-label={`Uploading ${i.file.name}`} />}
                </div>
                {i.documentId && (
                  <Link href={`/documents/${i.documentId}`} className="shrink-0 text-xs font-medium text-primary hover:underline">Open</Link>
                )}
                {(i.state === "pending") && (
                  <Button variant="ghost" size="icon-xs" aria-label={`Remove ${i.file.name}`} onClick={() => setItems((c) => c.filter((x) => x.id !== i.id))}>
                    <X className="size-3" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function StateIcon({ state }: { state: Item["state"] }) {
  const cls = "size-4 shrink-0";
  switch (state) {
    case "created": return <CheckCircle2 className={cn(cls, "text-success")} aria-label="Uploaded" />;
    case "duplicate": return <CopyCheck className={cn(cls, "text-info")} aria-label="Duplicate" />;
    case "rejected":
    case "error": return <AlertCircle className={cn(cls, "text-destructive")} aria-label="Failed" />;
    default: return <Loader2 className={cn(cls, "animate-spin text-muted-foreground motion-reduce:animate-none")} aria-label="Uploading" />;
  }
}
