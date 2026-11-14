"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, SendHorizontal, ShieldAlert, Square } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { AssistantMessage, UserBubble } from "@/components/assistant/message-view";
import { ConversationSidebar } from "@/components/assistant/conversation-sidebar";
import { ScopePicker } from "@/components/assistant/scope-picker";
import { SourcePanel } from "@/components/assistant/source-panel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useDebounced } from "@/hooks/use-debounced";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { chatService, type StreamHandlers } from "@/services/chat";
import { insightsService } from "@/services/insights";
import { uploadService } from "@/services/uploads";
import { atLeast, type Citation } from "@/types";

type Pending = { question: string | null; text: string; status: string; error?: string; retry?: () => void };

function Assistant() {
  const router = useRouter();
  const qc = useQueryClient();
  const activeId = useSearchParams().get("c");
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const config = useQuery({ queryKey: ["client-config"], queryFn: uploadService.config, staleTime: Infinity });

  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [draft, setDraft] = useState("");
  // The picker edits a local override; otherwise the opened conversation's saved scope applies.
  const [scopeEdit, setScopeEdit] = useState<{ id: string | null; ids: string[] } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sources, setSources] = useState<{ list: Citation[]; selected: number | null; open: boolean }>({ list: [], selected: null, open: false });
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const suggestions = useQuery({ queryKey: ["suggestions", ws], queryFn: () => insightsService.suggestions(ws!), enabled: !!ws && !activeId });
  const convs = useQuery({ queryKey: ["conversations", ws, q], queryFn: () => chatService.list(ws!, q || undefined), enabled: !!ws });
  const detail = useQuery({
    queryKey: ["conversation", ws, activeId],
    queryFn: () => chatService.get(ws!, activeId!),
    enabled: !!ws && !!activeId,
  });

  const scope = scopeEdit && scopeEdit.id === activeId ? scopeEdit.ids : (detail.data?.scope.document_ids ?? []);
  const setScope = (ids: string[]) => setScopeEdit({ id: activeId, ids });
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [detail.data?.messages.length, pending?.text, pending?.status]);

  const consentMissing = !!config.data?.external_ai_processing && workspace?.settings?.ai_processing_consent !== true;
  const canAsk = !!workspace && !consentMissing;
  const busy = !!pending && !pending.error;

  const refresh = useCallback(async (cid: string) => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["conversation", ws, cid] }),
      qc.invalidateQueries({ queryKey: ["conversations", ws] }),
      qc.invalidateQueries({ queryKey: ["overview", ws] }),
    ]);
  }, [qc, ws]);

  async function run(cid: string, start: (h: StreamHandlers, signal: AbortSignal) => Promise<void>, question: string | null) {
    const ac = new AbortController();
    abort.current = ac;
    let failed: string | undefined;
    setPending({ question, text: "", status: "understanding" });
    const handlers: StreamHandlers = {
      onStatus: (s) => setPending((p) => p && { ...p, status: s }),
      onToken: (t) => setPending((p) => p && { ...p, text: p.text + t }),
      onTitle: () => qc.invalidateQueries({ queryKey: ["conversations", ws] }),
      onError: (e) => { failed = e.message; },
    };
    try {
      await start(handlers, ac.signal);
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) failed = errorMessage(e);
    }
    abort.current = null;
    if (failed) {
      setPending((p) => ({ question: p?.question ?? question, text: "", status: "error", error: failed, retry: () => void retryLast(cid) }));
      await refresh(cid);
      return;
    }
    await refresh(cid);
    setPending(null);
  }

  async function ask(text: string) {
    if (!ws || !text.trim()) return;
    let cid = activeId;
    try {
      if (!cid) {
        const c = await chatService.create(ws, { document_ids: scope });
        cid = c.id;
        router.replace(`/assistant?c=${cid}`);
      } else if (detail.data && JSON.stringify(detail.data.scope.document_ids ?? []) !== JSON.stringify(scope)) {
        await chatService.update(ws, cid, { scope: { document_ids: scope } });
      }
    } catch (e) {
      toast.error(errorMessage(e));
      return;
    }
    setDraft("");
    const id = cid;
    await run(id, (h, s) => chatService.send(ws, id, text, h, s), text);
  }

  async function retryLast(cid: string) {
    if (!ws) return;
    const msgs = (await chatService.get(ws, cid)).messages;
    const last = msgs[msgs.length - 1];
    if (last?.role === "user") await run(cid, (h, s) => chatService.send(ws, cid, last.content, h, s), last.content);
  }

  const regenerate = () => activeId && ws && run(activeId, (h, s) => chatService.regenerate(ws, activeId, h, s), null);
  const stop = () => abort.current?.abort();

  const feedback = useMutation({
    mutationFn: ({ mid, rating }: { mid: string; rating: "up" | "down" | null }) => chatService.feedback(ws!, activeId!, mid, rating),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversation", ws, activeId] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => chatService.update(ws!, id, { title }),
    onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ["conversations", ws] }); qc.invalidateQueries({ queryKey: ["conversation", ws, v.id] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => chatService.remove(ws!, id),
    onSuccess: (_d, id) => {
      toast.success("Conversation deleted");
      qc.invalidateQueries({ queryKey: ["conversations", ws] });
      if (id === activeId) router.replace("/assistant");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const sidebar = (
    <ConversationSidebar
      items={convs.data ?? []} loading={convs.isLoading} activeId={activeId} search={search} onSearch={setSearch}
      onSelect={(id) => { router.push(`/assistant?c=${id}`); setHistoryOpen(false); }}
      onNew={() => { router.push("/assistant"); setHistoryOpen(false); }}
      onRename={(id, title) => rename.mutate({ id, title })} onDelete={(id) => remove.mutate(id)}
    />
  );

  const messages = detail.data?.messages ?? [];
  const lastAssistantIdx = messages.map((m) => m.role).lastIndexOf("assistant");
  const showPendingUser = pending?.question && !messages.some((m, i) => i === messages.length - 1 && m.role === "user" && m.content === pending.question);
  const empty = !activeId && !pending;

  return (
    <div className="-mx-4 -my-6 flex h-[calc(100svh-3.5rem)] sm:-mx-6 lg:-mx-8">
      <aside className="hidden w-72 shrink-0 border-r bg-card md:block">{sidebar}</aside>
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent side="left" className="w-80 p-0"><SheetTitle className="sr-only">Conversations</SheetTitle>{sidebar}</SheetContent>
      </Sheet>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-3 py-2 sm:px-5">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Conversation history" onClick={() => setHistoryOpen(true)}><History className="size-4" /></Button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{detail.data?.title ?? "New chat"}</h1>
          {ws && <ScopePicker workspaceId={ws} value={scope} onChange={setScope} disabled={busy} />}
        </header>

        <div className="flex-1 overflow-y-auto px-3 py-6 sm:px-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {consentMissing && (
              <div role="alert" className="flex gap-3 rounded-lg border border-warning/50 bg-warning/10 p-4 text-sm">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                <p>
                  External AI processing is not enabled for this workspace.{" "}
                  {atLeast(workspace?.role, "admin") ? <>Enable it in <Link href="/settings" className="font-medium underline">Settings</Link>.</> : "Ask a workspace admin to enable it."}
                </p>
              </div>
            )}
            {detail.isLoading && activeId && <Skeleton className="h-24" />}
            {detail.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(detail.error)}</p>}
            {empty && !consentMissing && (
              <div className="py-16 text-center">
                <h2 className="text-lg font-semibold">Ask your documents</h2>
                <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                  Answers are written only from your documents and every claim links to its source passage. Use the scope button to focus on specific documents.
                </p>
                {(suggestions.data?.length ?? 0) > 0 && (
                  <div className="mx-auto mt-6 flex max-w-xl flex-col gap-2" aria-label="Suggested questions">
                    {suggestions.data!.map((s) => (
                      <button key={s} type="button" onClick={() => void ask(s)} className="rounded-lg border bg-card px-4 py-2.5 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {messages.map((m, i) =>
              m.role === "user" ? (
                <UserBubble key={m.id} text={m.content} />
              ) : (
                <AssistantMessage
                  key={m.id} message={m} isLast={i === lastAssistantIdx && !pending}
                  onCite={(list, index) => setSources({ list, selected: index, open: true })}
                  onRegenerate={regenerate} onFeedback={(rating) => feedback.mutate({ mid: m.id, rating })}
                />
              ),
            )}
            {pending && (
              <>
                {showPendingUser && <UserBubble text={pending.question!} />}
                <AssistantMessage streamingText={pending.error ? "" : pending.text} status={pending.status} error={pending.error} onCite={() => {}} onRetry={pending.retry} />
              </>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <form
          className="border-t bg-background px-3 py-3 sm:px-6"
          onSubmit={(e) => { e.preventDefault(); if (!busy) void ask(draft); }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea
              aria-label="Your question" placeholder={consentMissing ? "AI processing is not enabled" : "Ask a question about your documents…"}
              value={draft} onChange={(e) => setDraft(e.target.value)} disabled={!canAsk} rows={1} maxLength={4000}
              className="max-h-40 min-h-10 resize-none"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy && draft.trim()) void ask(draft); } }}
            />
            {busy ? (
              <Button type="button" variant="outline" size="icon-lg" aria-label="Stop generating" onClick={stop}><Square className="size-4" /></Button>
            ) : (
              <Button type="submit" size="icon-lg" aria-label="Send" disabled={!canAsk || !draft.trim()}><SendHorizontal className="size-4" /></Button>
            )}
          </div>
          <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-muted-foreground">Enter to send, Shift+Enter for a new line. Answers can be wrong: check the cited sources.</p>
        </form>
      </section>

      <SourcePanel citations={sources.list} selected={sources.selected} open={sources.open} onOpenChange={(o) => setSources((s) => ({ ...s, open: o }))} />
    </div>
  );
}

export default function AssistantPage() {
  return <Suspense><Assistant /></Suspense>;
}

