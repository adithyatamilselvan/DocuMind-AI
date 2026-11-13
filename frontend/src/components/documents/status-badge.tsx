import { AlertCircle, CheckCircle2, Clock, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/types";

const LABEL: Record<DocumentStatus, string> = {
  UPLOADING: "Uploading",
  QUEUED: "Queued",
  PROCESSING: "Processing",
  EXTRACTING: "Extracting text",
  OCR_PROCESSING: "Running OCR",
  CHUNKING: "Chunking",
  EMBEDDING: "Embedding",
  INDEXING: "Indexing",
  COMPLETED: "Ready",
  FAILED: "Failed",
};

export const isInProgress = (s: DocumentStatus) => s !== "COMPLETED" && s !== "FAILED";

export function StatusBadge({ status }: { status: DocumentStatus }) {
  if (status === "COMPLETED")
    return (
      <Badge variant="outline" className="gap-1 border-success/40 text-success">
        <CheckCircle2 className="size-3" aria-hidden /> {LABEL[status]}
      </Badge>
    );
  if (status === "FAILED")
    return (
      <Badge variant="outline" className="gap-1 border-destructive/40 text-destructive">
        <AlertCircle className="size-3" aria-hidden /> {LABEL[status]}
      </Badge>
    );
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      {status === "QUEUED" || status === "UPLOADING" ? (
        <Clock className="size-3" aria-hidden />
      ) : (
        <Loader2 className="size-3 animate-spin motion-reduce:animate-none" aria-hidden />
      )}
      {LABEL[status]}
    </Badge>
  );
}
