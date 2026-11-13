import { FileSearch } from "lucide-react";

import { cn } from "@/lib/utils";

export function Brand({ className, showName = true }: { className?: string; showName?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <FileSearch className="size-4" aria-hidden />
      </span>
      {showName && <span className="text-base font-semibold tracking-tight">DocuMind</span>}
    </div>
  );
}
