"use client";

import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { markPassage, markTerm } from "@/lib/highlight";

type PdfJs = typeof import("pdfjs-dist");
let pdfjsPromise: Promise<PdfJs> | null = null;

/** Load PDF.js on demand (browser only) and point it at its bundled worker. */
function loadPdfJs(): Promise<PdfJs> {
  pdfjsPromise ??= import("pdfjs-dist").then((m) => {
    m.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
    return m;
  });
  return pdfjsPromise;
}

export function PdfViewer({
  url, page, scale, passage, search, onLoaded, onError,
}: {
  url: string;
  page: number;
  scale: number;
  passage?: string;
  search?: string;
  onLoaded: (numPages: number) => void;
  onError: (message: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [rendering, setRendering] = useState(true);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    let cancelled = false;
    let task: { promise: Promise<PDFDocumentProxy>; destroy: () => Promise<void> } | null = null;
    (async () => {
      try {
        const pdfjs = await loadPdfJs();
        task = pdfjs.getDocument({ url, withCredentials: true });
        const doc = await task.promise;
        if (cancelled) return;
        setPdf(doc);
        onLoaded(doc.numPages);
      } catch (e) {
        if (!cancelled) onError(e instanceof Error && e.name === "PasswordException" ? "This PDF is password protected." : "The PDF could not be displayed.");
      }
    })();
    return () => {
      cancelled = true;
      void task?.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    if (!pdf || page < 1 || page > pdf.numPages) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;
    let textLayer: { cancel: () => void } | null = null;
    (async () => {
      setRendering(true);
      const pdfjs = await loadPdfJs();
      const p = await pdf.getPage(page);
      if (cancelled) return;
      const viewport = p.getViewport({ scale });
      const canvas = canvasRef.current;
      const container = textRef.current;
      if (!canvas || !container) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      setSize({ w: viewport.width, h: viewport.height });
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      renderTask = p.render({ canvas, canvasContext: ctx, viewport, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined });
      container.replaceChildren();
      container.style.setProperty("--total-scale-factor", String(scale));
      const tl = new pdfjs.TextLayer({ textContentSource: p.streamTextContent(), container, viewport });
      textLayer = tl;
      try {
        await Promise.all([renderTask.promise, tl.render()]);
      } catch (e) {
        if ((e as Error).name === "RenderingCancelledException" || cancelled) return;
        onError("This page could not be rendered.");
        return;
      }
      if (cancelled) return;
      setRendering(false);
    })();
    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf, page, scale]);

  // Apply highlights whenever the text layer is (re)built or the passage / search term changes.
  useEffect(() => {
    const container = textRef.current;
    if (!container || rendering) return;
    const spans = Array.from(container.querySelectorAll<HTMLElement>(":scope > span")).filter((s) => !s.classList.contains("markedContent"));
    spans.forEach((s) => s.classList.remove("dm-hl", "dm-hl-cite"));
    const texts = spans.map((s) => s.textContent ?? "");
    if (passage) markPassage(texts, passage).forEach((i) => spans[i]?.classList.add("dm-hl-cite"));
    if (search) markTerm(texts, search).forEach((i) => spans[i]?.classList.add("dm-hl"));
    spans.find((s) => s.classList.contains("dm-hl-cite") || s.classList.contains("dm-hl"))?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [rendering, passage, search, page, scale]);

  return (
    <div className="relative mx-auto w-fit max-w-full overflow-auto rounded-md border bg-white shadow-sm" data-testid="pdf-page">
      {!pdf && <Skeleton className="h-[60svh] w-[min(40rem,90vw)]" />}
      <div className="relative" style={{ width: size.w || undefined, height: size.h || undefined }}>
        <canvas ref={canvasRef} className={pdf ? "block" : "hidden"} aria-label={`Page ${page}`} role="img" />
        <div ref={textRef} className="textLayer" />
      </div>
    </div>
  );
}
