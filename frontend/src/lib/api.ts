export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string | null,
  ) {
    super(message);
  }
}

const BASE = "/api/v1";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const NO_REDIRECT = [
  "/auth/login",
  "/auth/register",
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/verify-email",
];

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`))
    ?.split("=")[1];
}

export type Query = Record<string, string | number | boolean | undefined | null | string[]>;

type Options = {
  method?: string;
  body?: unknown;
  form?: FormData;
  query?: Query;
  signal?: AbortSignal;
};

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function csrfHeaders(method: string): Record<string, string> {
  if (!UNSAFE.has(method)) return {};
  const csrf = readCookie("documind_csrf");
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

export async function api<T = void>(path: string, opts: Options = {}): Promise<T> {
  const method = (opts.method ?? (opts.body || opts.form ? "POST" : "GET")).toUpperCase();
  const headers: Record<string, string> = { ...csrfHeaders(method) };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${BASE}${path}${buildQuery(opts.query)}`, {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: opts.signal,
  });
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const err = data?.error;
    if (res.status === 401 && typeof window !== "undefined" && !NO_REDIRECT.includes(path)) {
      // Full navigation on purpose: lets the proxy clear the stale HttpOnly cookie.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?expired=1");
    }
    throw new ApiError(
      res.status,
      err?.code ?? "http_error",
      err?.message ?? res.statusText ?? "Request failed",
      err?.details,
      err?.request_id,
    );
  }
  return data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
