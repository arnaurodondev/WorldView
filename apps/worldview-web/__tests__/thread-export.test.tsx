/**
 * __tests__/thread-export.test.tsx — markdown export tests
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08): the export must produce a stable
 * deterministic markdown string. Tests pin the format so that future
 * tweaks don't accidentally break downstream tooling consuming exported
 * files (e.g. a Notion-import bot).
 */

import { describe, it, expect, vi } from "vitest";
import {
  threadToMarkdown,
  downloadThread,
  slugify,
  yyyymmdd,
} from "@/lib/chat/export-thread";
import type { Thread, Message } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const THREAD: Thread = {
  thread_id: "t1",
  title: "NVDA earnings deep dive",
  owner_id: "u1",
  messages: [],
  created_at: "2026-04-10T09:00:00Z",
  updated_at: "2026-04-10T09:30:00Z",
};

const MESSAGES: Message[] = [
  {
    message_id: "m1",
    thread_id: "t1",
    role: "user",
    content: "What was NVDA's Q4 revenue?",
    created_at: "2026-04-10T09:00:01Z",
    citations: [],
  },
  {
    message_id: "m2",
    thread_id: "t1",
    role: "assistant",
    content: "$22.1B in Q4, up 22% YoY.",
    created_at: "2026-04-10T09:00:05Z",
    citations: [
      {
        article_id: "a1",
        title: "NVDA Q4 Earnings",
        url: "https://example.com/nvda-q4",
        source: "Reuters",
        relevance_score: 0.92,
      },
    ],
  },
];

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("slugify", () => {
  it("normalises titles to ASCII slugs", () => {
    expect(slugify("NVDA earnings deep dive")).toBe("nvda-earnings-deep-dive");
    expect(slugify("Hello / World!")).toBe("hello-world");
    expect(slugify("")).toBe("thread");
    expect(slugify(null)).toBe("thread");
  });
});

describe("yyyymmdd", () => {
  it("produces a UTC date stamp", () => {
    const stamp = yyyymmdd(new Date("2026-04-29T03:00:00Z"));
    expect(stamp).toBe("20260429");
  });
});

describe("threadToMarkdown", () => {
  it("renders title, role headings, content and citations", () => {
    const md = threadToMarkdown(
      THREAD,
      MESSAGES,
      new Date("2026-04-29T08:30:00Z"),
    );

    // Heading
    expect(md).toMatch(/^# Thread: NVDA earnings deep dive/);
    // Export timestamp
    expect(md).toContain("_Exported: 2026-04-29T08:30:00.000Z_");
    // Role headings
    expect(md).toContain("## User");
    expect(md).toContain("## Assistant");
    // Content
    expect(md).toContain("What was NVDA's Q4 revenue?");
    expect(md).toContain("$22.1B in Q4, up 22% YoY.");
    // Citation blockquote
    expect(md).toContain("> [1] Reuters — https://example.com/nvda-q4");
  });
});

describe("downloadThread", () => {
  it("calls URL.createObjectURL and triggers an <a download> click", () => {
    const createSpy = vi.fn(() => "blob:mock");
    const revokeSpy = vi.fn();
    // jsdom doesn't have createObjectURL — stub it.
    Object.defineProperty(global.URL, "createObjectURL", {
      value: createSpy,
      writable: true,
    });
    Object.defineProperty(global.URL, "revokeObjectURL", {
      value: revokeSpy,
      writable: true,
    });

    // Spy on document.createElement to capture the anchor click.
    const originalCreate = document.createElement.bind(document);
    let capturedAnchor: HTMLAnchorElement | null = null;
    const createSpyDoc = vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreate(tag);
      if (tag === "a") {
        capturedAnchor = el as HTMLAnchorElement;
        // Stub click to avoid jsdom navigation noise.
        (el as HTMLAnchorElement).click = vi.fn();
      }
      return el;
    });

    downloadThread(THREAD, MESSAGES);

    expect(createSpy).toHaveBeenCalled();
    expect(capturedAnchor).not.toBeNull();
    expect(capturedAnchor!.download).toMatch(/^thread-nvda-earnings-deep-dive-\d{8}\.md$/);

    createSpyDoc.mockRestore();
  });
});
