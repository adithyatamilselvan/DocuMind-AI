import { ApiError, api, csrfHeaders } from "@/lib/api";
import { readSse } from "@/lib/sse";
import type { ChatMessage, Citation, Conversation, ConversationDetail, DocumentText, Scope } from "@/types";

export type StreamHandlers = {
  onUserMessage?: (id: string) => void;
  onTitle?: (title: string) => void;
  onStatus?: (stage: string) => void;
  onSources?: (sources: { label: string; title: string; page: number | null }[]) => void;
  onToken?: (text: string) => void;
  onFinal?: (f: FinalEvent) => void;
  onError?: (e: { code: string; message: string; retryable?: boolean }) => void;
};

export type FinalEvent = {
  message_id: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  insufficient_evidence: boolean;
  warnings: string[];
};

const base = (ws: string) => `/api/v1/workspaces/${ws}/conversations`;

async function consume(res: Response, h: StreamHandlers) {
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    let code = "http_error";
    try {
      const j = await res.json();
      msg = j.error?.message ?? msg;
      code = j.error?.code ?? code;
    } catch {
      /* not JSON */
    }
    if (res.status === 401) {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?expired=1");
    }
    throw new ApiError(res.status, code, msg);
  }
  for await (const { event, data } of readSse(res.body)) {
    const d = data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    switch (event) {
      case "user_message": h.onUserMessage?.(d.id); break;
      case "title": h.onTitle?.(d.title); break;
      case "status": h.onStatus?.(d.stage); break;
      case "retrieval": h.onSources?.(d.sources); break;
      case "token": h.onToken?.(d.text); break;
      case "final": h.onFinal?.(d as FinalEvent); break;
      case "error": h.onError?.(d as { code: string; message: string }); break;
    }
  }
}

async function post(url: string, body: unknown, h: StreamHandlers, signal?: AbortSignal) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...csrfHeaders("POST") },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  await consume(res, h);
}

export const chatService = {
  list: (ws: string, q?: string) => api<Conversation[]>(`/workspaces/${ws}/conversations`, { query: { q } }),
  get: (ws: string, id: string) => api<ConversationDetail>(`/workspaces/${ws}/conversations/${id}`),
  create: (ws: string, scope?: Scope) =>
    api<Conversation>(`/workspaces/${ws}/conversations`, { body: { scope: scope ?? {} } }),
  update: (ws: string, id: string, body: { title?: string; scope?: Scope }) =>
    api<Conversation>(`/workspaces/${ws}/conversations/${id}`, { method: "PATCH", body }),
  remove: (ws: string, id: string) => api(`/workspaces/${ws}/conversations/${id}`, { method: "DELETE" }),
  feedback: (ws: string, cid: string, mid: string, rating: "up" | "down" | null) =>
    api(`/workspaces/${ws}/conversations/${cid}/messages/${mid}/feedback`, { method: "PUT", body: { rating } }),
  send: (ws: string, id: string, content: string, h: StreamHandlers, signal?: AbortSignal) =>
    post(`${base(ws)}/${id}/messages`, { content }, h, signal),
  regenerate: (ws: string, id: string, h: StreamHandlers, signal?: AbortSignal) =>
    post(`${base(ws)}/${id}/regenerate`, undefined, h, signal),
  documentText: (ws: string, id: string) => api<DocumentText>(`/workspaces/${ws}/documents/${id}/text`),
};

export type { ChatMessage };
