/**
 * components/intelligence/HealthScoreBadge.tsx — Circular progress ring for health score
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY A CIRCULAR RING:
 * A circular progress ring is the standard UI pattern for a single percentage
 * metric that is simultaneously a score (0–1 scale) and a status indicator
 * (green/yellow/red). It is more visually distinctive than a linear bar and
 * fits well in the sidebar's compact header area alongside the entity name.
 *
 * WHY SVG STROKE-DASHARRAY TRICK:
 * SVG circles can't have a partially-filled stroke natively. The trick:
 *   1. Set stroke-dasharray to the full circumference (2πr)
 *   2. Set stroke-dashoffset to (1 - score) * circumference
 * This creates the appearance of a partial circle filled to the score fraction.
 * No JavaScript animation library needed — pure SVG geometry.
 *
 * COLOR THRESHOLDS:
 *   < 0.3  → red (negative) — entity data is severely incomplete/stale
 *   0.3-0.6→ amber (warning) — moderate data quality
 *   > 0.6  → green (positive) — healthy entity with good coverage
 *
 * WHO USES IT: EntitySidebar header
 * DATA SOURCE: health_score from useEntityIntelligence
 */

// WHY no "use client": pure props-based display component with no hooks.
// The parent handles data fetching.

// ── Props ─────────────────────────────────────────────────────────────────────

interface HealthScoreBadgeProps {
  /** Health score 0.0–1.0, or null if not yet computed */
  score: number | null;
  /** Circle diameter in pixels. Default 48. */
  size?: number;
  /** Additional className */
  className?: string;
}

// ── Color helpers ─────────────────────────────────────────────────────────────

/**
 * scoreColor — maps health score to a semantic CSS color class.
 *
 * WHY semantic classes (not hardcoded hex): the palette is defined in globals.css
 * as CSS variables. Using Tailwind semantic tokens means the badge automatically
 * respects any future palette updates.
 */
function scoreColor(score: number): { stroke: string; text: string } {
  if (score < 0.3) return { stroke: "text-negative", text: "text-negative" };
  if (score < 0.6) return { stroke: "text-warning", text: "text-warning" };
  return { stroke: "text-positive", text: "text-positive" };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HealthScoreBadge({
  score,
  size = 48,
  className = "",
}: HealthScoreBadgeProps) {
  const radius = (size - 6) / 2; // WHY -6: 3px stroke width each side
  const circumference = 2 * Math.PI * radius;
  const normalizedScore = score == null ? 0 : Math.max(0, Math.min(1, score));

  // WHY (1 - normalizedScore) * circumference:
  // dashoffset=0 → full ring drawn (100% score)
  // dashoffset=circumference → empty ring (0% score)
  // Subtracting from full gives "filled to score" appearance.
  const dashOffset = (1 - normalizedScore) * circumference;

  const { stroke: strokeClass, text: textClass } = score != null
    ? scoreColor(score)
    : { stroke: "text-muted-foreground", text: "text-muted-foreground" };

  const displayPct = score != null ? Math.round(score * 100) : "—";

  return (
    <div
      className={`relative inline-flex items-center justify-center ${className}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Health score: ${score != null ? `${Math.round(score * 100)}%` : "not available"}`}
    >
      <svg
        width={size}
        height={size}
        // WHY -90 degree rotation: SVG arcs start at the right (3 o'clock).
        // Rotating -90deg makes the arc start at the top (12 o'clock), which
        // is the conventional starting point for progress rings.
        style={{ transform: "rotate(-90deg)" }}
        aria-hidden="true"
      >
        {/* Background track circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={3}
          className="text-muted/60 stroke-current"
        />
        {/* Progress arc — inherits strokeClass color via currentColor */}
        {normalizedScore > 0 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            strokeWidth={3}
            // WHY currentColor: lets Tailwind's text color class control the stroke.
            className={`stroke-current ${strokeClass}`}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
          />
        )}
      </svg>

      {/* Score text centered inside the ring */}
      <span
        className={`absolute text-[11px] font-mono font-semibold tabular-nums ${textClass}`}
        aria-hidden="true"
      >
        {typeof displayPct === "number" ? `${displayPct}` : "—"}
      </span>
    </div>
  );
}
