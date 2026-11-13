import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, buildQuery } from "./api";

function mockFetch(status: number, body?: unknown) {
  const fn = vi.fn().mockImplementation(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: body === undefined ? {} : { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("buildQuery", () => {
  it("skips empty values and repeats arrays", () => {
    expect(buildQuery({ q: "a b", page: 2, empty: "", none: undefined, tag: ["x", "y"] })).toBe(
      "?q=a+b&page=2&tag=x&tag=y",
    );
    expect(buildQuery({})).toBe("");
  });
});

describe("api", () => {
  beforeEach(() => {
    document.cookie = "documind_csrf=abc123";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends CSRF header on unsafe methods only", async () => {
    const fn = mockFetch(200, { ok: true });
    await api("/x", { body: { a: 1 } });
    expect(fn.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("abc123");
    expect(fn.mock.calls[0][1].method).toBe("POST");
    await api("/x");
    expect(fn.mock.calls[1][1].headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("returns undefined for 204", async () => {
    mockFetch(204);
    await expect(api("/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps the backend error envelope to ApiError", async () => {
    mockFetch(409, { error: { code: "email_taken", message: "Taken", request_id: "r1" } });
    const err = await api("/auth/register", { body: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "email_taken", message: "Taken", requestId: "r1" });
  });
});
