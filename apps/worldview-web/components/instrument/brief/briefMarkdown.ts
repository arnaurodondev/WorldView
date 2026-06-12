/**
 * components/instrument/brief/briefMarkdown.ts — instrument-brief markdown parsing
 *
 * WHY THIS EXISTS (Wave-2 brief redesign, 2026-06-10): the S8 instrument brief
 * arrives as structured markdown:
 *
 *   ## LEAD
 *   One-sentence takeaway. [c6][c7]
 *   ---
 *   ## DETAILS
 *   ### Entity Overview
 *   - bullet [c1]
 *   ...
 *
 * The old AiBriefBanner dumped this RAW into a <p whitespace-pre-wrap> — the
 * analyst saw literal "## LEAD" hashes and "[c12]" citation tokens. This
 * module is the single place that understands the brief's shape:
 *
 *   - `stripCitationMarkers` removes the `[cN]` (and bare `[N]`) source
 *     tokens — the banner has no citation side-panel, so the tokens are
 *     pure noise here (the Chat surface, which CAN resolve them, keeps them).
 *   - `parseInstrumentBrief` splits the narrative into { lead, body } so the
 *     banner can render the LEAD prominently and the DETAILS as collapsible
 *     structured markdown.
 *
 * WHY a pure module (no React): trivially unit-testable, and the parsing is
 * reusable if another surface (e.g. a hover-card) ever needs the lead line.
 */

/**
 * stripCitationMarkers — remove inline citation tokens from brief text.
 *
 * Handles BOTH token styles the S8 prompts have emitted:
 *   - `[c12]` — instrument-brief style (citation id prefixed with "c")
 *   - `[12]`  — legacy/morning-brief style (bare index, capped at 2 digits
 *               to avoid eating real bracketed numbers like "[2026]")
 *
 * Leading whitespace before a token is consumed too, so "fact. [c1][c2]"
 * collapses to "fact." (no dangling double-spaces).
 */
export function stripCitationMarkers(text: string): string {
  return text.replace(/\s*\[c?\d{1,2}\]/g, "");
}

export interface ParsedBrief {
  /** The LEAD sentence(s) — citation-stripped plain text, no heading chrome. */
  lead: string;
  /**
   * Everything after the lead (the DETAILS sections) as citation-stripped
   * markdown. The redundant "## DETAILS" heading and the `---` rule are
   * dropped (the banner provides its own visual structure); the `###`
   * sub-headings are KEPT — they are the brief's real information hierarchy.
   */
  body: string;
}

/**
 * parseInstrumentBrief — split a brief narrative into lead + body.
 *
 * PARSING STRATEGY (deliberately forgiving — LLM output drifts):
 *   1. If a "## LEAD" heading exists, the lead is everything from it to the
 *      next `---` rule or `##` heading.
 *   2. Otherwise the first non-empty paragraph is the lead (older briefs and
 *      morning-brief-shaped narratives have no LEAD heading).
 *   3. The body is everything that follows, minus the "## DETAILS" heading
 *      line and separator rules.
 *
 * Both halves are citation-stripped. Empty body → body === "" (the banner
 * then renders the lead only, with no expand affordance for an empty shell).
 */
export function parseInstrumentBrief(narrative: string): ParsedBrief {
  const text = narrative.trim();

  // ── Locate the LEAD section ────────────────────────────────────────────────
  const leadHeading = /^##\s*LEAD\s*$/im;
  const leadMatch = leadHeading.exec(text);

  let leadRaw: string;
  let bodyRaw: string;

  if (leadMatch) {
    const afterHeading = text.slice(leadMatch.index + leadMatch[0].length);
    // The lead ends at the first horizontal rule or the next ## heading,
    // whichever comes first. (The live format uses "---" then "## DETAILS".)
    const endMatch = /^(?:---+|##\s)/m.exec(afterHeading);
    if (endMatch) {
      leadRaw = afterHeading.slice(0, endMatch.index);
      bodyRaw = afterHeading.slice(endMatch.index);
    } else {
      leadRaw = afterHeading;
      bodyRaw = "";
    }
  } else {
    // Fallback: first paragraph = lead, the rest = body. WHY split on blank
    // line: markdown's paragraph boundary; robust to single-paragraph briefs.
    const paragraphs = text.split(/\n\s*\n/);
    leadRaw = paragraphs[0] ?? "";
    bodyRaw = paragraphs.slice(1).join("\n\n");
  }

  // ── Clean the body ─────────────────────────────────────────────────────────
  // Drop separator rules and the redundant "## DETAILS" heading line; keep
  // every ### sub-heading and bullet (that's the content hierarchy).
  const body = stripCitationMarkers(
    bodyRaw
      .split("\n")
      .filter((line) => !/^\s*---+\s*$/.test(line) && !/^##\s*DETAILS\s*$/i.test(line.trim()))
      .join("\n"),
  ).trim();

  // The lead renders as plain styled text (not markdown), so also strip any
  // residual markdown emphasis tokens that would read as literal characters.
  const lead = stripCitationMarkers(leadRaw).replace(/\*\*?/g, "").trim();

  return { lead, body };
}

/**
 * isBriefStale — true when the brief is older than the staleness budget.
 *
 * WHY 24h: instrument briefs regenerate at most hourly on demand, but a brief
 * older than a trading day can predate market-moving news — the banner shows
 * an amber STALE tag so the analyst weighs it accordingly. Invalid/missing
 * timestamps count as stale (we can't vouch for unknown freshness).
 */
export const BRIEF_STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export function isBriefStale(generatedAtIso: string | null | undefined, now: Date = new Date()): boolean {
  if (!generatedAtIso) return true;
  const t = new Date(generatedAtIso).getTime();
  if (!Number.isFinite(t)) return true;
  return now.getTime() - t > BRIEF_STALE_AFTER_MS;
}
