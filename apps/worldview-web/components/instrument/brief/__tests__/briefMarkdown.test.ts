/**
 * components/instrument/brief/__tests__/briefMarkdown.test.ts
 *
 * WHY THIS EXISTS (Wave-2 brief redesign): pins the brief-narrative parsing
 * contract against the LIVE S8 format (verified 2026-06-10 against AAPL):
 *
 *   ## LEAD\n<takeaway> [c6][c7]\n---\n## DETAILS\n### Section\n- bullet [c1]
 *
 * The old banner rendered this raw (literal "## LEAD" + "[c12]" tokens on
 * screen). These tests guarantee the parser strips the chrome and splits
 * lead/body correctly — including the fallback paths for older briefs that
 * have no LEAD heading.
 */

import { describe, it, expect } from "vitest";
import {
  parseInstrumentBrief,
  stripCitationMarkers,
  isBriefStale,
} from "@/components/instrument/brief/briefMarkdown";

// Live-shaped fixture (abbreviated from the real AAPL brief).
const LIVE_NARRATIVE = [
  "## LEAD",
  "Apple's WWDC26 Siri AI rollout marks a critical step, but the stock declined on the announcement. [c6][c7][c12]",
  "",
  "---",
  "",
  "## DETAILS",
  "### Entity Overview",
  "- Apple Inc. (AAPL) is classified within the Information Technology sector. [c1]",
  "",
  "### Recent Developments",
  "- [2026-06-08] Apple unveiled Siri AI at WWDC26. [c6][c7]",
].join("\n");

describe("stripCitationMarkers", () => {
  it("removes [cN] tokens including the leading space", () => {
    expect(stripCitationMarkers("fact. [c6][c12]")).toBe("fact.");
  });

  it("removes bare [N] tokens (legacy style) but not 4-digit years", () => {
    expect(stripCitationMarkers("see [3] for detail")).toBe("see for detail");
    // [2026] is 4 digits — must survive (date-like bracket content).
    expect(stripCitationMarkers("- [2026] guidance")).toBe("- [2026] guidance");
  });
});

describe("parseInstrumentBrief", () => {
  it("extracts the LEAD sentence without heading chrome or citations", () => {
    const { lead } = parseInstrumentBrief(LIVE_NARRATIVE);
    expect(lead).toBe(
      "Apple's WWDC26 Siri AI rollout marks a critical step, but the stock declined on the announcement.",
    );
    // The raw markdown chrome must NOT leak into the lead.
    expect(lead).not.toContain("##");
    expect(lead).not.toContain("[c");
  });

  it("keeps ### sub-headings in the body but drops '## DETAILS' and '---'", () => {
    const { body } = parseInstrumentBrief(LIVE_NARRATIVE);
    expect(body).toContain("### Entity Overview");
    expect(body).toContain("### Recent Developments");
    expect(body).not.toMatch(/^##\s*DETAILS/m);
    expect(body).not.toMatch(/^---/m);
    expect(body).not.toContain("[c1]");
    // Date brackets in bullets survive (they are content, not citations).
    expect(body).toContain("[2026-06-08]");
  });

  it("falls back to first-paragraph lead when there is no LEAD heading", () => {
    const { lead, body } = parseInstrumentBrief(
      "Apple beat EPS by 5c on iPhone strength.\n\nMore detail in the second paragraph.",
    );
    expect(lead).toBe("Apple beat EPS by 5c on iPhone strength.");
    expect(body).toBe("More detail in the second paragraph.");
  });

  it("returns an empty body for a single-paragraph brief (no expand shell)", () => {
    const { lead, body } = parseInstrumentBrief("One-liner brief.");
    expect(lead).toBe("One-liner brief.");
    expect(body).toBe("");
  });
});

describe("isBriefStale", () => {
  const now = new Date("2026-06-10T12:00:00Z");

  it("fresh brief (1h old) is not stale", () => {
    expect(isBriefStale("2026-06-10T11:00:00Z", now)).toBe(false);
  });

  it("brief older than 24h is stale", () => {
    expect(isBriefStale("2026-06-09T11:00:00Z", now)).toBe(true);
  });

  it("missing or invalid timestamps count as stale (unknown freshness)", () => {
    expect(isBriefStale(null, now)).toBe(true);
    expect(isBriefStale("not-a-date", now)).toBe(true);
  });
});
