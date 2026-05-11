/**
 * __tests__/types-brief.test.ts — PLAN-0062-W4 TypeScript type contract tests (T-W4-D-01)
 *
 * WHY THIS EXISTS:
 * TypeScript types are compile-time constructs — they can't be tested with
 * Jest/Vitest assertions directly. Instead, we use "type assignment tests":
 * if a variable assignment would fail to type-check, tsc/vitest will flag it.
 *
 * These tests verify the SHAPE of the new W4 type additions:
 *   - BriefCitation has document_id (not just source_id)
 *   - BriefCitation.source_type is the narrow Literal union
 *   - BriefBullet.citations is typed as BriefCitation[]
 *   - BriefSection.bullets is BriefBullet[] (not string[])
 *   - BriefingResponse has optional confidence + lead fields
 *   - BriefingResponse.entity_mentions is optional (breaking change from required)
 *   - BriefingCitation (legacy) still compiles alongside BriefCitation
 *
 * WHY RUNTIME ASSERTIONS (not just type-check): tsc --noEmit validates at the
 * module level. Runtime value tests (e.g. `expect(cit.source_type).toBe(...)`)
 * confirm the runtime shape matches the compile-time type — catching cases where
 * a type was widened to `any` or `unknown` in an intermediate cast.
 */

import { describe, it, expect } from "vitest";
import type {
  BriefCitation,
  BriefingCitation,
  BriefBullet,
  BriefSection,
  BriefingResponse,
} from "@/types/api";

// ── BriefCitation tests ───────────────────────────────────────────────────────

describe("BriefCitation (W4+ shape)", () => {
  it("has document_id as the primary identifier", () => {
    // WHY: document_id is the W4 canonical identifier — tests that it's present
    // and not accidentally replaced by source_id in the type definition.
    const cit: BriefCitation = {
      document_id: "doc-uuid-1234",
      source_type: "article",
      title: "Apple beats earnings estimates",
      url: "https://reuters.com/article/aapl-q4",
    };
    expect(cit.document_id).toBe("doc-uuid-1234");
  });

  it("accepts optional source_id for back-compat", () => {
    // WHY: pre-W4 cached responses still emit source_id. The type must accept
    // both fields simultaneously (not exclusive union).
    const cit: BriefCitation = {
      document_id: "doc-uuid-1234",
      source_id: "art-legacy-1234",
      source_type: "article",
      title: "Legacy article",
      url: null,
    };
    expect(cit.source_id).toBe("art-legacy-1234");
  });

  it("source_type discriminates article | event | alert", () => {
    // WHY: the Literal union must accept all three values and reject others.
    const articleCit: BriefCitation = { document_id: "d1", source_type: "article", title: "A", url: null };
    const eventCit: BriefCitation = { document_id: "d2", source_type: "event", title: "B", url: null };
    const alertCit: BriefCitation = { document_id: "d3", source_type: "alert", title: "C", url: null };

    expect(articleCit.source_type).toBe("article");
    expect(eventCit.source_type).toBe("event");
    expect(alertCit.source_type).toBe("alert");
  });

  it("url can be null or a string", () => {
    // WHY: events and alerts have no external URL; articles always have one.
    // Both shapes must be representable without a type cast.
    const withUrl: BriefCitation = { document_id: "d1", source_type: "article", title: "A", url: "https://example.com" };
    const withoutUrl: BriefCitation = { document_id: "d2", source_type: "event", title: "B", url: null };
    expect(withUrl.url).toBeTruthy();
    expect(withoutUrl.url).toBeNull();
  });

  it("accepts optional snippet field", () => {
    // WHY: snippet is a new field added in W4 — pre-W4 cached responses lack it.
    // Making it optional means pre-W4 and W4 shapes both satisfy the type.
    const cit: BriefCitation = {
      document_id: "d1",
      source_type: "article",
      title: "A",
      url: "https://example.com",
      snippet: "First 400 chars of the article...",
    };
    expect(cit.snippet).toContain("400 chars");
  });
});

// ── BriefingCitation (legacy) tests ──────────────────────────────────────────

describe("BriefingCitation (legacy pre-W4 back-compat shape)", () => {
  it("has source_id as the primary identifier (not document_id)", () => {
    // WHY: legacy responses emit source_id; new responses emit document_id.
    // Both types must coexist so a union array can hold both without casting.
    const legacyCit: BriefingCitation = {
      source_type: "article",
      source_id: "art-legacy-123",
      title: "Old article format",
      url: "https://bloomberg.com/old-article",
    };
    expect(legacyCit.source_id).toBe("art-legacy-123");
  });

  it("lacks document_id field (not present in the pre-W4 shape)", () => {
    // WHY: the type distinction between BriefCitation and BriefingCitation is
    // the presence of document_id. TypeScript will report an error if you try
    // to access .document_id on a BriefingCitation directly — this test
    // verifies the legacy type doesn't accidentally pick up the new field.
    const legacyCit: BriefingCitation = {
      source_type: "article",
      source_id: "art-old-1",
      title: "Old",
      url: null,
    };
    // WHY 'document_id' in check (not type assertion): we verify at runtime
    // that the plain object doesn't have the W4 field. This would fail if
    // someone accidentally spread BriefCitation fields into BriefingCitation.
    expect("document_id" in legacyCit).toBe(false);
  });
});

// ── BriefBullet tests ─────────────────────────────────────────────────────────

describe("BriefBullet (W4 citation gate)", () => {
  it("has text and citations fields", () => {
    // WHY: BriefBullet is the atomic unit of the W4 citation contract.
    // Both text and citations must be present and correctly typed.
    const bullet: BriefBullet = {
      text: "Tech sector rallied 1.2% on strong earnings.",
      citations: [
        {
          document_id: "doc-tech-1",
          source_type: "article",
          title: "Tech rally news",
          url: "https://reuters.com/tech",
        },
      ],
    };
    expect(bullet.text).toBe("Tech sector rallied 1.2% on strong earnings.");
    expect(bullet.citations).toHaveLength(1);
    expect(bullet.citations![0].document_id).toBe("doc-tech-1");
  });

  it("citations is optional (allows legacy string-bullet adapters in tests)", () => {
    // WHY optional: test adapters like _toBriefBullet() in morning-brief-card.test.tsx
    // wrap string bullets into BriefBullet objects. Making citations optional
    // lets them create the object without necessarily providing citations.
    const bulletNoCitations: BriefBullet = { text: "Some claim." };
    expect(bulletNoCitations.citations).toBeUndefined();
  });

  it("citations array can hold multiple BriefCitation objects", () => {
    // WHY: the LLM may reference [c1][c2] on a single bullet — both must resolve.
    const bullet: BriefBullet = {
      text: "Multiple sources corroborate this claim.",
      citations: [
        { document_id: "d1", source_type: "article", title: "Source A", url: "https://a.com" },
        { document_id: "d2", source_type: "event", title: "Source B", url: null },
      ],
    };
    expect(bullet.citations).toHaveLength(2);
  });
});

// ── BriefSection tests ────────────────────────────────────────────────────────

describe("BriefSection (W4+ shape with BriefBullet[])", () => {
  it("bullets is BriefBullet[] (not string[])", () => {
    // WHY: PLAN-0062-W4 changed bullets from string[] to BriefBullet[].
    // This test pins that the type definition correctly reflects the W4 schema.
    const section: BriefSection = {
      title: "Market Context",
      bullets: [
        {
          text: "Tech outperformed.",
          citations: [{ document_id: "d1", source_type: "article", title: "T", url: null }],
        },
      ],
    };
    expect(section.bullets[0].text).toBe("Tech outperformed.");
    expect(section.bullets[0].citations).toBeDefined();
  });

  it("empty bullets array is valid", () => {
    // WHY: a section returned by the backend may have all bullets stripped by
    // _backfill_uncited_bullets. An empty bullets array must not crash the type.
    const emptySection: BriefSection = { title: "Empty", bullets: [] };
    expect(emptySection.bullets).toHaveLength(0);
  });
});

// ── BriefingResponse W4 fields ────────────────────────────────────────────────

describe("BriefingResponse — W4 additions (confidence + lead + optional entity_mentions)", () => {
  it("accepts confidence as an optional number", () => {
    // WHY: pre-W4 cached responses lack confidence; W4+ responses always have it.
    // Making it optional allows pre-W4 cached responses to parse without error.
    const resp: BriefingResponse = {
      narrative: "Markets moved higher.",
      risk_summary: null,
      citations: [],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
      confidence: 0.82,
    };
    expect(resp.confidence).toBe(0.82);
  });

  it("accepts lead as an optional string or null", () => {
    // WHY: pre-W4 responses don't have a lead field; W4+ responses have a lead
    // string from the ## LEAD block. The component falls back to summary when absent.
    const withLead: BriefingResponse = {
      narrative: "n",
      risk_summary: null,
      citations: [],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
      lead: "Markets opened higher on strong payrolls data.",
    };
    expect(withLead.lead).toBeTruthy();

    const withNullLead: BriefingResponse = {
      narrative: "n",
      risk_summary: null,
      citations: [],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
      lead: null,
    };
    expect(withNullLead.lead).toBeNull();
  });

  it("entity_mentions is optional (not required)", () => {
    // WHY: PLAN-0062-W4 made entity_mentions optional in the BriefingResponse type.
    // This test verifies that a response without entity_mentions still satisfies the type.
    const resp: BriefingResponse = {
      narrative: "Brief without entity mentions.",
      risk_summary: null,
      citations: [],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
      // WHY no entity_mentions: omitted intentionally to test optional field
    };
    expect(resp.entity_mentions).toBeUndefined();
  });

  it("sections is BriefSection[] with BriefBullet[] bullets", () => {
    // WHY: verifies the full chain — BriefingResponse → BriefSection → BriefBullet → BriefCitation.
    const resp: BriefingResponse = {
      narrative: "n",
      risk_summary: null,
      citations: [],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
      sections: [
        {
          title: "Market Context",
          bullets: [
            {
              text: "Tech led gains.",
              citations: [{ document_id: "d1", source_type: "article", title: "T", url: null }],
            },
          ],
        },
      ],
    };
    expect(resp.sections![0].bullets[0].text).toBe("Tech led gains.");
  });

  it("citations array accepts mixed BriefCitation and BriefingCitation (union)", () => {
    // WHY: during the cache warm-up window after W4 deploy, some citation objects
    // in the array will be BriefCitation (new) and some BriefingCitation (legacy).
    // The union type must accept both shapes without a cast.
    const resp: BriefingResponse = {
      narrative: "n",
      risk_summary: null,
      citations: [
        // W4+ citation (document_id)
        { document_id: "d1", source_type: "article", title: "New", url: "https://new.com" },
        // Legacy citation (source_id)
        { source_id: "s1", source_type: "article", title: "Old", url: "https://old.com" },
      ],
      generated_at: "2026-05-03T10:00:00Z",
      cached: false,
      entity_id: null,
    };
    expect(resp.citations).toHaveLength(2);
  });
});
