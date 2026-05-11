/**
 * lib/chat/export-thread.ts — markdown export for chat threads
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-07):
 * Analysts often want to paste a research conversation into a Notion page,
 * a Google doc, or a Slack message. A markdown download is the lowest-
 * friction format: every doc tool accepts it. We assemble the entire thread
 * — title + ISO timestamp + each message + per-message citations — into a
 * single .md file and trigger a browser download.
 *
 * WHY pure functions + a thin downloader: separating threadToMarkdown (pure)
 * from downloadThread (DOM side-effects) makes the markdown logic trivially
 * unit-testable (T-E-5-08).
 *
 * WHY citation rendering uses blockquotes: pasting into most markdown viewers
 * keeps citations visually distinct from the answer body. Inline links would
 * also work but blockquotes survive plain-text paste better.
 */

import type { Thread, Message } from "@/types/api";

// ── Slug helper ───────────────────────────────────────────────────────────────

/**
 * slugify — turn a thread title into a filesystem-safe slug.
 *
 * WHY: filenames with spaces, slashes, or unicode are a UX hazard in browser
 * downloads. Stripping to lowercase ASCII + dashes keeps it portable across
 * macOS, Windows and Linux.
 *
 * @param input  raw title (or null/undefined for placeholder)
 * @returns      stable slug, never empty (falls back to "thread")
 */
export function slugify(input: string | null | undefined): string {
  const s = (input ?? "thread").toLowerCase();
  // Replace any non-alphanumeric run with a single hyphen, collapse hyphens.
  const cleaned = s
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60); // WHY 60 char cap: keeps full filename under most FS limits.
  return cleaned || "thread";
}

// ── Date helper ───────────────────────────────────────────────────────────────

/**
 * yyyymmdd — UTC date stamp like "20260429" used in the output filename.
 *
 * WHY UTC: trader machines roam time zones. Using local time would make the
 * same export filename differ across machines. UTC is reproducible.
 */
export function yyyymmdd(date = new Date()): string {
  const y = date.getUTCFullYear().toString();
  const m = (date.getUTCMonth() + 1).toString().padStart(2, "0");
  const d = date.getUTCDate().toString().padStart(2, "0");
  return `${y}${m}${d}`;
}

// ── Markdown formatter ────────────────────────────────────────────────────────

/**
 * threadToMarkdown — produce a portable .md document representing the
 * thread + every message + every citation.
 *
 * Format (deterministic):
 *
 *   # Thread: <title>
 *
 *   _Exported: 2026-04-29T08:30:00.000Z_
 *
 *   ## User
 *
 *   ...question...
 *
 *   ## Assistant
 *
 *   ...answer...
 *
 *   > [1] Source — https://...
 *   > [2] Source — https://...
 */
export function threadToMarkdown(
  thread: Thread,
  messages: Message[],
  exportedAt: Date = new Date(),
): string {
  const lines: string[] = [];

  // Title — fall back to a placeholder when S9 hasn't named the thread yet.
  lines.push(`# Thread: ${thread.title ?? "Untitled"}`);
  lines.push("");
  lines.push(`_Exported: ${exportedAt.toISOString()}_`);
  lines.push("");

  // Loop messages in order. We rely on the caller passing the chronological
  // list (the chat page already maintains this in localMessages).
  for (const msg of messages) {
    // WHY explicit role headings: makes the export readable when pasted into
    // a plain text editor without markdown rendering.
    const heading = msg.role === "user" ? "## User" : "## Assistant";
    lines.push(heading);
    lines.push("");
    // WHY trim trailing whitespace: SSE-streamed answers occasionally end
    // with a newline that adds empty lines in the export.
    lines.push(msg.content.trimEnd());
    lines.push("");

    // Citations as a quote block with [N] index, source, URL.
    if (msg.citations && msg.citations.length > 0) {
      for (let i = 0; i < msg.citations.length; i++) {
        const c = msg.citations[i];
        const url = c.url ? c.url : "(no url)";
        lines.push(`> [${i + 1}] ${c.source} — ${url}`);
      }
      lines.push("");
    }
  }

  return lines.join("\n");
}

// ── Browser download trigger ──────────────────────────────────────────────────

/**
 * downloadThread — produce the markdown and trigger a browser download.
 *
 * Filename format:  thread-<slug>-YYYYMMDD.md
 *
 * WHY URL.createObjectURL + anchor click: this is the canonical "force a
 * download from generated content" pattern. We revoke the URL after a tick
 * so memory isn't leaked when the user exports many threads.
 */
export function downloadThread(thread: Thread, messages: Message[]): void {
  const md = threadToMarkdown(thread, messages);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  const filename = `thread-${slugify(thread.title)}-${yyyymmdd()}.md`;

  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // WHY append+click+remove: needed by Firefox; Chrome works without DOM
  // attachment but keeping the cross-browser path is harmless.
  document.body.appendChild(a);
  a.click();
  a.remove();

  // Revoke after the next tick so the download has time to start.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
