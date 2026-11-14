import { describe, expect, it } from "vitest";

import { countOccurrences, markPassage, markTerm, norm, splitByTerm } from "./highlight";

const spans = ["Quarterly revenue grew", "twelve percent in", "Europe, driven by", "strong demand.", "Unrelated footer"];

describe("norm", () => {
  it("collapses whitespace and unifies punctuation", () => {
    expect(norm("  A  “B”\n—  c ")).toBe('a "b" - c');
  });
});

describe("markPassage", () => {
  it("marks every span the passage covers, across span boundaries", () => {
    const hit = markPassage(spans, "Quarterly revenue grew twelve percent in Europe, driven by strong demand.");
    expect([...hit].sort()).toEqual([0, 1, 2, 3]);
  });

  it("falls back to a shorter prefix when the tail differs from the text layer", () => {
    const hit = markPassage(spans, "Quarterly revenue grew twelve percent in Europe, driven by weak demand elsewhere in the world today");
    expect([...hit]).toContain(0);
    expect([...hit]).not.toContain(4);
  });

  it("marks nothing when the passage is absent", () => {
    expect(markPassage(spans, "completely different passage about biology").size).toBe(0);
  });
});

describe("markTerm / countOccurrences / splitByTerm", () => {
  it("finds a term case-insensitively, including when it spans two spans", () => {
    expect([...markTerm(spans, "percent in europe")].sort()).toEqual([1, 2]);
    expect(markTerm(spans, "x").size).toBe(0);
  });
  it("counts occurrences", () => {
    expect(countOccurrences("Revenue, revenue and REVENUE.", "revenue")).toBe(3);
    expect(countOccurrences("abc", "")).toBe(0);
  });
  it("splits text for <mark> rendering without interpreting regex characters", () => {
    expect(splitByTerm("a.b and a.b", "a.b")).toEqual([
      { text: "a.b", match: true }, { text: " and ", match: false }, { text: "a.b", match: true },
    ]);
    expect(splitByTerm("(x)", "(x)")[0].match).toBe(true);
  });
});
