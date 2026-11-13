import { describe, expect, it } from "vitest";

import { formatBytes, formatPercent } from "./format";

describe("format", () => {
  it("formats bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(50 * 1024 * 1024)).toBe("50 MB");
  });
  it("formats percent and missing values", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(null)).toBe("—");
  });
});
