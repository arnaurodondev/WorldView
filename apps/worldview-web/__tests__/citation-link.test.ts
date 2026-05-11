/**
 * __tests__/citation-link.test.ts — Citation deep-link helpers (T-W4-D-03)
 *
 * WHY THIS EXISTS:
 * The citation-link.ts helpers are pure functions — they're the easiest
 * module to test in isolation and the most critical for the "Top Stories"
 * chip rendering in MorningBriefCard and the CitationChips sub-component.
 *
 * These tests verify:
 *   - resolveCitationLink dispatches correctly per source_type + url presence
 *   - getCitationSourceId handles both BriefCitation (document_id) and
 *     BriefingCitation (source_id) shapes
 *   - getCitationDomain strips www. and handles malformed URLs gracefully
 */

import { describe, it, expect } from "vitest";
import {
  resolveCitationLink,
  getCitationSourceId,
  getCitationDomain,
} from "@/components/brief/citation-link";
import type { BriefCitation, BriefingCitation } from "@/types/api";

// ── resolveCitationLink tests ─────────────────────────────────────────────────

describe("resolveCitationLink", () => {
  it("returns external href for article citation with URL", () => {
    // WHY: news articles always open in a new tab (external publisher URL).
    const cit: BriefCitation = {
      document_id: "d1",
      source_type: "article",
      title: "Apple earnings",
      url: "https://reuters.com/aapl-q4",
    };
    const result = resolveCitationLink(cit);
    expect(result.kind).toBe("external");
    if (result.kind === "external") {
      expect(result.href).toBe("https://reuters.com/aapl-q4");
    }
  });

  it("returns none for article citation with null URL", () => {
    // WHY: shouldn't happen in W4+ responses (all articles have URLs), but
    // we guard it defensively so pre-W4 data doesn't crash the chip renderer.
    const cit: BriefCitation = {
      document_id: "d2",
      source_type: "article",
      title: "No URL article",
      url: null,
    };
    const result = resolveCitationLink(cit);
    expect(result.kind).toBe("none");
  });

  it("returns none for event citation (no detail page yet)", () => {
    // WHY: economic events don't have a navigable S9 detail page in the current
    // platform version. The chip renders as plain text, not a link.
    const cit: BriefCitation = {
      document_id: "evt-1",
      source_type: "event",
      title: "CPI release",
      url: null,
    };
    const result = resolveCitationLink(cit);
    expect(result.kind).toBe("none");
  });

  it("returns none for alert citation", () => {
    // WHY: alerts link to the alert drawer (JS-side action), not a URL.
    const cit: BriefCitation = {
      document_id: "alert-1",
      source_type: "alert",
      title: "Price spike alert",
      url: null,
    };
    const result = resolveCitationLink(cit);
    expect(result.kind).toBe("none");
  });

  it("works with legacy BriefingCitation shape (source_id)", () => {
    // WHY: pre-W4 cached citations use BriefingCitation — the helper must
    // accept both shapes via the union parameter type.
    const legacyCit: BriefingCitation = {
      source_id: "art-legacy-1",
      source_type: "article",
      title: "Legacy article",
      url: "https://bloomberg.com/legacy",
    };
    const result = resolveCitationLink(legacyCit);
    expect(result.kind).toBe("external");
    if (result.kind === "external") {
      expect(result.href).toBe("https://bloomberg.com/legacy");
    }
  });
});

// ── getCitationSourceId tests ─────────────────────────────────────────────────

describe("getCitationSourceId", () => {
  it("returns document_id for W4+ BriefCitation", () => {
    // WHY: W4+ responses use document_id — must be the primary key for React list rendering.
    const cit: BriefCitation = {
      document_id: "doc-uuid-w4",
      source_type: "article",
      title: "W4 article",
      url: null,
    };
    expect(getCitationSourceId(cit)).toBe("doc-uuid-w4");
  });

  it("returns source_id for legacy BriefingCitation", () => {
    // WHY: pre-W4 citations use source_id — the helper must fall back correctly.
    const legacyCit: BriefingCitation = {
      source_id: "art-legacy-456",
      source_type: "article",
      title: "Old article",
      url: "https://old.com",
    };
    expect(getCitationSourceId(legacyCit)).toBe("art-legacy-456");
  });
});

// ── getCitationDomain tests ───────────────────────────────────────────────────

describe("getCitationDomain", () => {
  it("extracts host from https URL and strips www.", () => {
    // WHY: chip labels show "bloomberg.com" not "www.bloomberg.com".
    const cit: BriefCitation = {
      document_id: "d1",
      source_type: "article",
      title: "Bloomberg article",
      url: "https://www.bloomberg.com/news/articles/2026-05-01/aapl",
    };
    expect(getCitationDomain(cit)).toBe("bloomberg.com");
  });

  it("keeps non-www subdomains (finance.yahoo.com)", () => {
    // WHY: "finance.yahoo.com" is a distinct property from "yahoo.com" —
    // stripping it would give the user a misleading source label.
    const cit: BriefCitation = {
      document_id: "d2",
      source_type: "article",
      title: "Yahoo Finance",
      url: "https://finance.yahoo.com/news/aapl-earnings",
    };
    expect(getCitationDomain(cit)).toBe("finance.yahoo.com");
  });

  it("returns 'source' for null URL", () => {
    // WHY: events and alerts have null URLs — we still render a chip label.
    const cit: BriefCitation = {
      document_id: "d3",
      source_type: "event",
      title: "CPI release",
      url: null,
    };
    expect(getCitationDomain(cit)).toBe("source");
  });

  it("returns 'source' for malformed URL (never throws)", () => {
    // WHY: a bad URL in the citation must not crash the chip renderer.
    // This can happen with legacy data or encoding issues in article URLs.
    const cit: BriefCitation = {
      document_id: "d4",
      source_type: "article",
      title: "Broken URL",
      url: "not-a-valid-url",
    };
    expect(getCitationDomain(cit)).toBe("source");
  });

  it("works with legacy BriefingCitation shape", () => {
    // WHY: the helper is used in the Top Stories chip renderer which
    // receives both BriefCitation and BriefingCitation objects.
    const legacyCit: BriefingCitation = {
      source_id: "s1",
      source_type: "article",
      title: "Reuters",
      url: "https://www.reuters.com/world/us/",
    };
    expect(getCitationDomain(legacyCit)).toBe("reuters.com");
  });
});
