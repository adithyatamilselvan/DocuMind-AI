import { ApiError, api, csrfHeaders } from "@/lib/api";
import type { ClientConfig, ProcessingInfo, UploadResponse, UploadResult, VersionItem } from "@/types";

/** XHR (not fetch) so we can report real upload progress. */
function sendForm<T>(
  url: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    for (const [k, v] of Object.entries(csrfHeaders("POST"))) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error body */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data as T);
      // Full navigation on purpose so the proxy can clear the stale cookie.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      if (xhr.status === 401) window.location.assign("/login?expired=1");
      const err = (data as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error;
      reject(new ApiError(xhr.status, err?.code ?? "http_error", err?.message ?? "Upload failed", undefined, err?.request_id));
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "Network error during upload"));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload cancelled"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

const base = (ws: string) => `/api/v1/workspaces/${ws}/documents`;

export const uploadService = {
  config: () => api<ClientConfig>("/system/config"),
  async uploadOne(ws: string, file: File, onProgress?: (f: number) => void, signal?: AbortSignal): Promise<UploadResult> {
    const form = new FormData();
    form.append("files", file);
    const res = await sendForm<UploadResponse>(`${base(ws)}/upload`, form, onProgress, signal);
    return res.results[0];
  },
  uploadVersion(ws: string, id: string, file: File, onProgress?: (f: number) => void): Promise<UploadResult> {
    const form = new FormData();
    form.append("file", file);
    return sendForm<UploadResult>(`${base(ws)}/${id}/versions`, form, onProgress);
  },
  retry: (ws: string, id: string) => api(`/workspaces/${ws}/documents/${id}/retry`, { method: "POST" }),
  versions: (ws: string, id: string) => api<VersionItem[]>(`/workspaces/${ws}/documents/${id}/versions`),
  processing: (ws: string, id: string) => api<ProcessingInfo | null>(`/workspaces/${ws}/documents/${id}/processing`),
  downloadUrl: (ws: string, id: string, opts?: { version?: string; inline?: boolean }) => {
    const p = new URLSearchParams();
    if (opts?.version) p.set("version", opts.version);
    if (opts?.inline) p.set("inline", "true");
    const q = p.toString();
    return `${base(ws)}/${id}/download${q ? `?${q}` : ""}`;
  },
};
