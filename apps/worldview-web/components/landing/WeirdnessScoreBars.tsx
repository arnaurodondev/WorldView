/**
 * components/landing/WeirdnessScoreBars.tsx — weirdness sub-score breakdown
 *
 * WHY THIS EXISTS: The signature "Weird Connections" feature scores how
 * surprising an indirect path between two entities is. The composite weirdness
 * is a product of four sub-scores (reliability × unexpectedness × semantic
 * distance × novelty). This component renders those four mini-bars plus the
 * highlighted composite, mirroring the in-product citation-confidence bar
 * visual language (design spec §5b / §6.14).
 *
 * WHY COLOUR-BLIND-SAFE (§6.11b): colour alone (green/amber/red) is invisible
 * to ~8% of men with deuteranopia/protanopia. Every bar therefore carries a
 * REDUNDANT numeric label (e.g. "0.91") AND an `aria-label` describing the
 * band in words ("high"/"medium"/"low"). The fill colour is a secondary, not
 * primary, signal — the number is always present.
 *
 * WHY SERVER COMPONENT: static, no interactivity.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §5b, §6.14.
 */

/**
 * Score band thresholds (mirrors the §6.14 citation-confidence bands):
 *   - high   ≥ 0.7   (green / positive)
 *   - medium 0.4–0.7 (amber / warning)
 *   - low    < 0.4   (red / negative)
 *
 * EXPORTED so the unit test can assert the thresholds directly without
 * rendering — see WeirdnessScoreBars.test.tsx.
 */
export type ScoreBand = "high" | "medium" | "low";

export function scoreBand(value: number): ScoreBand {
  if (value >= 0.7) return "high";
  if (value >= 0.4) return "medium";
  return "low";
}

/**
 * bandColor — map a band to a semantic Tailwind fill token. Returns the
 * background class for the bar fill. Colour is the SECONDARY cue (the numeric
 * label is the primary, colour-blind-safe one).
 */
function bandColor(band: ScoreBand): string {
  if (band === "high") return "bg-positive";
  if (band === "medium") return "bg-warning";
  return "bg-negative";
}

export interface ScoreItem {
  label: string;
  value: number; // 0..1
}

export interface WeirdnessScoreBarsProps {
  scores: ScoreItem[];
  /** The composite weirdness score (highlighted, rendered last). */
  composite: number;
}

/**
 * Bar — one labelled score row: label · track+fill · numeric value.
 *
 * The track is `role="img"` with an `aria-label` so a screen reader announces
 * "Reliability: 0.91 (high)" as a single unit rather than reading the visual
 * fill width (which it cannot perceive).
 */
function Bar({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  const band = scoreBand(value);
  // Clamp to [0,1] then to a percentage for the fill width.
  const pct = Math.max(0, Math.min(1, value)) * 100;

  return (
    <div className="grid grid-cols-[7.5rem,1fr,2.5rem] items-center gap-3">
      <span
        className={`font-mono text-[11px] ${
          emphasis ? "font-semibold text-foreground" : "text-muted-foreground"
        }`}
      >
        {label}
      </span>

      {/* Track + fill. role="img" + aria-label makes the bar self-describing
          to assistive tech; the visible numeric label (next cell) is the
          colour-blind-safe redundant signal. */}
      <div
        role="img"
        aria-label={`${label}: ${value.toFixed(2)} (${band})`}
        className="h-2 w-full overflow-hidden rounded-[2px] bg-muted"
      >
        <div
          className={`h-full rounded-[2px] ${
            // The composite row always uses the brand primary so it stands out
            // as the headline number; the sub-scores use band colours.
            emphasis ? "bg-primary" : bandColor(band)
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <span
        className={`text-right font-mono text-[11px] tabular-nums ${
          emphasis ? "font-semibold text-primary" : "text-foreground"
        }`}
      >
        {value.toFixed(2)}
      </span>
    </div>
  );
}

export function WeirdnessScoreBars({ scores, composite }: WeirdnessScoreBarsProps) {
  return (
    <div className="space-y-2.5">
      {scores.map((s) => (
        <Bar key={s.label} label={s.label} value={s.value} />
      ))}

      {/* Composite — visually separated and emphasised in primary. */}
      <div className="mt-3 border-t border-border/40 pt-3">
        <Bar label="Weirdness" value={composite} emphasis />
      </div>
    </div>
  );
}
