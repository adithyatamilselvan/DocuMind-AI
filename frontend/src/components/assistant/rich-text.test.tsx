import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RichText, parseBlocks, parseInline } from "./rich-text";

describe("parseBlocks", () => {
  it("splits paragraphs, bullets and numbered lists", () => {
    expect(parseBlocks("Intro\n\n- a\n- b\n\n1. x\n2. y")).toEqual([
      { type: "p", text: "Intro" },
      { type: "ul", items: ["a", "b"] },
      { type: "ol", items: ["x", "y"] },
    ]);
  });
});

describe("parseInline", () => {
  it("finds bold, code and citation markers", () => {
    expect(parseInline("a **b** `c` [2]")).toEqual([
      { type: "text", text: "a " },
      { type: "bold", text: "b" },
      { type: "text", text: " " },
      { type: "code", text: "c" },
      { type: "text", text: " " },
      { type: "cite", index: 2 },
    ]);
  });
});

describe("RichText", () => {
  it("renders only real citations as buttons and reports clicks", () => {
    const onCite = vi.fn();
    render(<RichText text="Revenue grew [1]. Odd marker [9]." citedIndexes={new Set([1])} onCite={onCite} />);
    fireEvent.click(screen.getByRole("button", { name: "Open source 1" }));
    expect(onCite).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("button", { name: "Open source 9" })).toBeNull();
    expect(screen.getByText(/Odd marker \[9\]/)).toBeInTheDocument();
  });

  it("never interprets HTML in model output", () => {
    const { container } = render(<RichText text={'<img src=x onerror="alert(1)"> **ok**'} citedIndexes={new Set()} onCite={() => {}} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
  });
});
