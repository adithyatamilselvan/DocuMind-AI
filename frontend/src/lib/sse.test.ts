import { describe, expect, it } from "vitest";

import { parseBlock, readSse } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      chunks.forEach((x) => c.enqueue(enc.encode(x)));
      c.close();
    },
  });
}

describe("sse", () => {
  it("parses a block", () => {
    expect(parseBlock('event: token\ndata: {"text":"hi"}')).toEqual({ event: "token", data: { text: "hi" } });
    expect(parseBlock("event: x")).toBeNull();
    expect(parseBlock("event: x\ndata: not-json")).toBeNull();
  });

  it("reassembles events split across arbitrary chunk boundaries", async () => {
    const full = 'event: token\ndata: {"text":"héllo"}\n\nevent: final\ndata: {"ok":true}\n\n';
    const bytes = new TextEncoder().encode(full);
    // split in the middle of the multi-byte "é" and of the event separator
    const cut = [bytes.slice(0, 30), bytes.slice(30, 31), bytes.slice(31, 33), bytes.slice(33)];
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        cut.forEach((b) => c.enqueue(b));
        c.close();
      },
    });
    const out = [];
    for await (const e of readSse(body)) out.push(e);
    expect(out).toEqual([
      { event: "token", data: { text: "héllo" } },
      { event: "final", data: { ok: true } },
    ]);
  });

  it("handles a trailing event without a final blank line", async () => {
    const out = [];
    for await (const e of readSse(streamOf(['event: done\ndata: {}']))) out.push(e);
    expect(out).toEqual([{ event: "done", data: {} }]);
  });
});
