/**
 * components/landing/ProductShot.tsx — reusable window-chrome screenshot frame
 *
 * WHY THIS EXISTS: The landing redesign (docs/design/2026-06-23-landing-page-
 * redesign.md §2) replaces hand-built ASCII/CSS mocks with REAL product
 * screenshots. Every screenshot is shown inside an identical macOS-style
 * window-chrome frame so the marketing page reads as "this is the actual app",
 * not a stock illustration. Hero, FeatureGrid tiles, and the KG spotlight all
 * reuse this one component for visual consistency.
 *
 * WHY SERVER COMPONENT: pure render, no interactivity. Uses `next/image` with
 * explicit width/height to reserve layout space and prevent CLS (Cumulative
 * Layout Shift) while the PNG decodes.
 *
 * WHY A GRACEFUL FALLBACK: the screenshots are captured by a separate Playwright
 * script (`capture-landing-shots.mjs`) against the running platform. If those
 * PNGs are not present yet, `next/image` would still try to load them and show
 * a broken-image icon. To keep the build green and the page presentable BEFORE
 * captures run, callers can pass `placeholder` — when set, we render a tasteful
 * mono placeholder panel instead of the <Image>. The caller decides per-shot.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §2
 * (ProductShot row), §0 design-system guardrails (rounded-[2px], semantic
 * tokens, mono labels).
 */

import Image from "next/image";

export interface ProductShotProps {
  /** Public path to the screenshot, e.g. "/landing/hero-intelligence.png". */
  src: string;
  /** Descriptive alt text — REQUIRED for a11y (screen readers + SEO). */
  alt: string;
  /** Mono label shown in the window-chrome title bar, e.g. "intelligence". */
  label: string;
  /** Intrinsic pixel width of the image (prevents CLS). Default 1280. */
  width?: number;
  /** Intrinsic pixel height of the image (prevents CLS). Default 800. */
  height?: number;
  /**
   * Show a green "LIVE" pill on the right of the chrome bar. Purely cosmetic —
   * signals "this product is alive" the same way the Hero terminal does.
   */
  live?: boolean;
  /**
   * Eager-load this image (set true ONLY for the above-the-fold hero shot).
   * Everything else lazy-loads to keep the marketing page TTFB fast.
   */
  priority?: boolean;
  /**
   * When true, render a mono placeholder panel instead of <Image>. Used until
   * the real screenshot has been captured by capture-landing-shots.mjs. Keeps
   * the build green and the layout intact with zero broken-image icons.
   */
  placeholder?: boolean;
  /** Extra classes applied to the outer frame (e.g. shadow tuning per usage). */
  className?: string;
}

export function ProductShot({
  src,
  alt,
  label,
  width = 1280,
  height = 800,
  live = false,
  priority = false,
  placeholder = false,
  className = "",
}: ProductShotProps) {
  return (
    <div
      className={`relative overflow-hidden rounded-[2px] border border-border/60 bg-card shadow-2xl ${className}`}
    >
      {/* macOS-style window chrome — same visual language as the Hero card.
          WHY semantic tokens (destructive/primary/positive) not raw hex: the
          design system bans raw hex outside JSON-LD (§0); these three tokens
          read as the canonical red/amber/green window dots. */}
      <div className="flex items-center gap-2 border-b border-border/50 bg-muted/30 px-3 py-2">
        <div className="flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-destructive/70" />
          <span className="h-2.5 w-2.5 rounded-full bg-primary/70" />
          <span className="h-2.5 w-2.5 rounded-full bg-positive/70" />
        </div>
        <span className="ml-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
          worldview · {label}
        </span>
        {live && (
          // No animate-pulse on the dot (§0 guardrail forbids it on status
          // dots); a static green dot still reads as "live".
          <span className="ml-auto inline-flex items-center gap-1.5 font-mono text-[9px] text-muted-foreground/60">
            <span className="h-1.5 w-1.5 rounded-full bg-positive" />
            LIVE
          </span>
        )}
      </div>

      {placeholder ? (
        // ── Fallback panel (screenshot not captured yet) ─────────────────────
        // A tasteful mono panel that fills the same aspect ratio the real
        // image will occupy, so swapping in the PNG later causes no reflow.
        <div
          role="img"
          aria-label={alt}
          // Reserve the same aspect ratio as the eventual image so there's no
          // layout shift when the real PNG drops in.
          style={{ aspectRatio: `${width} / ${height}` }}
          className="flex w-full flex-col items-center justify-center gap-2 bg-muted/20 p-8 text-center"
        >
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground/70">
            {label}
          </span>
          <span className="max-w-xs font-mono text-[10px] leading-relaxed text-muted-foreground/40">
            {/* TODO(landing-shots): replace with real capture from
                capture-landing-shots.mjs → {src} */}
            screenshot pending capture
          </span>
        </div>
      ) : (
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          priority={priority}
          // sizes hint lets next/image pick the right responsive variant; the
          // frame is full-width on mobile and roughly half-width at lg.
          sizes="(max-width: 1024px) 100vw, 50vw"
          className="h-auto w-full"
        />
      )}
    </div>
  );
}
