/**
 * components/feedback/ScreenshotCapture.tsx — opt-in DOM screenshot capture.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-03):
 * Bug reports without a screenshot are 10x harder to triage. We use
 * html2canvas to rasterise the current viewport into a PNG data URI, then
 * surface a preview the user can confirm or discard before attaching to
 * the feedback payload.
 *
 * WHY OPT-IN: Approved decision (PLAN-0053 Wave G open question 3).
 * Screenshots can leak sensitive info; the user must explicitly press
 * "Capture screenshot" — we never auto-capture.
 *
 * HOW THE OUTPUT IS PASSED ON (updated by PLAN-0053 QA-iter1 F-003):
 * We expose a `data:image/png;base64,…` URL via the `onCapture` callback.
 * The parent FeedbackModal forwards it inside the JSON `console_logs`
 * column (NOT `screenshot_url`, which the backend validates as HTTPS-
 * only). The data URI is capped at 1MB before send; larger captures are
 * dropped with a `screenshot_data_uri_truncated: true` flag so operators
 * can see the user attempted a screenshot. When a presigned-S3 upload
 * route lands (future wave) we will switch to that and use the proper
 * `screenshot_url` field.
 *
 * BLUR TOOL (V1 LITE): Approved spec calls for a blur tool. A full
 * canvas-based redaction editor is out of scope here. This component
 * exposes a simpler "blur entire screenshot" toggle — the user gets a
 * Gaussian-blurred PNG instead of the raw one. A future wave can swap in
 * a region-select editor without breaking the API surface.
 *
 * SECURITY:
 *   - html2canvas runs in the browser only — no server-side render
 *   - We dynamic-import html2canvas so SSR + initial bundle stays small
 *   - The data URI lives in React state; never persisted
 */

"use client";
// WHY "use client": dynamic-imports html2canvas, manipulates DOM canvas,
// uses useState — all browser-only.

import { useCallback, useState } from "react";
import { Camera, X, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";

// ── Props ──────────────────────────────────────────────────────────────────

export interface ScreenshotCaptureProps {
  /**
   * Called with the captured PNG data URI when the user confirms a capture,
   * or `null` when they discard it.
   */
  onCapture: (dataUrl: string | null) => void;
  /** Whether the parent currently holds a captured image (for label flip). */
  hasCapture: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * blurCanvas — apply a CSS-level blur to a canvas via 2D filter.
 *
 * WHY filter (not getImageData + JS box blur): the 2D context's `filter`
 * property runs in the browser's image pipeline (GPU-accelerated where
 * available) and is ~100x faster than a JS implementation for full-frame
 * blur. The trade-off is browser-version sensitivity; modern Chromium
 * and Firefox both support it.
 */
function blurCanvas(source: HTMLCanvasElement): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = source.width;
  out.height = source.height;
  const ctx = out.getContext("2d");
  if (!ctx) return source;
  ctx.filter = "blur(8px)";
  ctx.drawImage(source, 0, 0);
  return out;
}

// ── Component ──────────────────────────────────────────────────────────────

export function ScreenshotCapture({ onCapture, hasCapture }: ScreenshotCaptureProps) {
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [blur, setBlur] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * captureNow — runs html2canvas against document.body. We hide the
   * feedback modal momentarily by toggling a class so the screenshot
   * doesn't include the modal itself.
   */
  const captureNow = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      // WHY dynamic import: html2canvas is ~150 KB minified. Loading it
      // only when the user clicks "Capture" keeps the initial route
      // bundle small and avoids loading it for the 90% of users who
      // never use feedback.
      const { default: html2canvas } = await import("html2canvas");

      // Hide our own modal during capture by setting visibility on a
      // well-known wrapper id. The FeedbackModal mounts with this id
      // (see FeedbackModal.tsx).
      const modal = document.getElementById("worldview-feedback-modal-root");
      const previousVisibility = modal?.style.visibility ?? "";
      if (modal) modal.style.visibility = "hidden";

      let canvas: HTMLCanvasElement;
      try {
        canvas = await html2canvas(document.body, {
          // WHY useCORS: the images come from same-origin S9; CORS-safe
          // is the most permissive "best effort" mode.
          useCORS: true,
          // WHY scale 1: keep file size reasonable. 2x doubles bytes.
          scale: 1,
          // WHY logging false: html2canvas spams console.log otherwise.
          logging: false,
        });
      } finally {
        // Always restore visibility — even on capture failure.
        if (modal) modal.style.visibility = previousVisibility;
      }

      const finalCanvas = blur ? blurCanvas(canvas) : canvas;
      const dataUrl = finalCanvas.toDataURL("image/png");
      setPreview(dataUrl);
      onCapture(dataUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Capture failed.");
    } finally {
      setBusy(false);
    }
  }, [blur, onCapture]);

  const discard = useCallback(() => {
    setPreview(null);
    onCapture(null);
  }, [onCapture]);

  return (
    <div className="space-y-2 rounded-[2px] border border-border bg-card/50 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">Screenshot (optional)</span>
        {/* Blur toggle — a single switch is V1 lite for the "blur tool" spec. */}
        <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <input
            type="checkbox"
            checked={blur}
            onChange={(e) => setBlur(e.target.checked)}
            className="h-3 w-3"
            // Tiny checkbox sized for the dense settings row.
          />
          Blur entire screenshot
        </label>
      </div>

      {/* WHY dual buttons: Capture and Discard live side-by-side so the
          user can iterate quickly. */}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={captureNow}
          disabled={busy}
        >
          <Camera className="mr-1.5 h-3.5 w-3.5" />
          {busy ? "Capturing…" : hasCapture ? "Recapture" : "Capture screenshot"}
        </Button>
        {hasCapture && (
          <Button type="button" variant="ghost" size="sm" onClick={discard}>
            <X className="mr-1.5 h-3.5 w-3.5" />
            Discard
          </Button>
        )}
      </div>

      {/* Preview — small thumbnail; clicking expands to full size in a new tab. */}
      {preview && (
        <div className="mt-2 flex flex-col gap-1">
          <a
            href={preview}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[10px] text-muted-foreground underline hover:text-foreground"
          >
            <Eye className="h-3 w-3" />
            Open full preview
          </a>
          {/* PLAN-0053 QA-iter2 F-iter2-004: warn the user when the capture
              exceeds the 1MB JSON column cap and will be dropped server-side.
              The data URI base64-bloats by ~33% so the threshold here is
              conservative (1.4MB raw → ~1.05MB encoded). */}
          {preview.length > 1_048_576 && (
            <p className="text-[10px] text-warning">
              ⚠ Screenshot is over 1MB and will not be sent. Try capturing
              a narrower view or disabling the blur filter.
            </p>
          )}
        </div>
      )}

      {error && (
        <p className="text-[10px] text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
