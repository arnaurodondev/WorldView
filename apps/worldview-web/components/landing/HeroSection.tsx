/**
 * components/landing/HeroSection.tsx — landing page hero (T-A-1-01)
 *
 * WHY THIS EXISTS: The first 600px of the landing page must (a) name the
 * product, (b) state the value, (c) give two CTAs, and (d) prove the product
 * is real with a live-feeling terminal mock — all above the fold.
 *
 * WHY SERVER COMPONENT: Fully static; pre-rendered at build time for fast TTFB.
 * The "animation" is pure CSS (animate-pulse on the live dot, transition on
 * hover) — no client JavaScript needed.
 *
 * COMPETITIVE BENCHMARK: Bloomberg.com, IBKR, TradingView all open with a tag
 * line + 2 CTAs + product visual. The terminal mock sets us apart from
 * generic SaaS landing pages by signalling "professional tool, not a toy".
 *
 * DESIGN REFERENCE:
 *   PLAN-0052 Wave A T-A-1-01
 *   docs/audits/2026-04-28-qa-frontend-design-roadmap.md PART B (Phase 4)
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";

/**
 * TERMINAL_LINES — ASCII workspace mock displayed in the hero card.
 *
 * WHY ASCII over screenshot: ships zero bytes, never goes stale, renders
 * identically on every OS (box-drawing chars are universal in system fonts).
 * Communicates "keyboard-first terminal" to the target audience (PMs/quants
 * who use Bloomberg daily) before they even click.
 *
 * The 11px monospace + 1.6 line-height makes box-drawing characters visually
 * connect cleanly without gaps between rows.
 */
const TERMINAL_LINES = [
  "┌─ WATCHLIST ─────┬─ AAPL · 189.25 ──────────┐",
  "│ AAPL    +1.24% │ Mkt Cap     2.94T        │",
  "│ MSFT    -0.51% │ P/E         28.4x        │",
  "│ NVDA    +3.42% │ EPS         6.42         │",
  "│ TSLA    -2.13% │ ─────────────────────────│",
  "│ AMZN    +0.81% │ News    Earnings beat …  │",
  "│ META    +1.07% │ Impact  +0.62 (HIGH)     │",
  "└─────────────────┴──────────────────────────┘",
] as const;

export function HeroSection() {
  return (
    <section
      id="hero"
      // WHY pt-20 not pt-14: the sticky nav is 56px tall; this gives the hero
      // breathing room below it on desktop without crowding mobile.
      // WHY relative + overflow-hidden: anchor the radial gradient ::before
      // glow inside the section without leaking into adjacent sections.
      className="relative overflow-hidden border-b border-border/40 bg-background"
    >
      {/* WHY two radial glows (top-right + bottom-left): asymmetric ambient light
          gives depth without using a hard background image. The amber tint at top
          right hints at the brand color; the negative-space at bottom-left
          mirrors the data-density message. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background:radial-gradient(80%_60%_at_85%_-10%,hsl(var(--primary)/0.08)_0%,transparent_60%),radial-gradient(60%_50%_at_-10%_120%,hsl(var(--positive)/0.05)_0%,transparent_60%)]"
      />

      <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-6 py-20 lg:grid-cols-[minmax(0,1fr),minmax(0,1.1fr)] lg:gap-20 lg:px-8 lg:py-24">
        {/* ── Left column: copy + CTAs ──────────────────────────────────── */}
        <div>
          {/* Eyebrow / kicker — sets product category before the heading.
              Mono small caps mirrors Bloomberg / Refinitiv style guides. */}
          <p className="mb-5 inline-flex items-center gap-2 rounded-[2px] border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
            Market Intelligence Terminal
          </p>

          {/* WHY this headline structure: short product name first; secondary
              line tells the user what they get. Tested copy pattern from
              Bloomberg Pro, IBKR, and TradingView landing pages. */}
          <h1 className="mb-6 text-4xl font-semibold leading-[1.05] tracking-tight text-foreground sm:text-5xl lg:text-[3.5rem]">
            Bloomberg-grade research,
            <br />
            <span className="text-primary">without the Bloomberg bill.</span>
          </h1>

          <p className="mb-8 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            Real-time market signals, AI-powered news intelligence, and an
            entity knowledge graph — built on EODHD data and externalized LLMs
            for full data sovereignty.
          </p>

          {/* ── CTA pair ───────────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/register"
              data-testid="hero-primary-cta"
              className="group inline-flex items-center gap-2 rounded-[2px] bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30"
            >
              Open the terminal free
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>

            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-[2px] border border-border/60 px-6 py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              Sign in
            </Link>
          </div>

          {/* Sub-CTA explainer — short risk-reduction copy under the CTAs.
              Conversion best practice: address the "what's the catch?" thought. */}
          {/* QA iter-1 (a11y M3): bumped opacity from /70 → default
              text-muted-foreground for AA contrast on this informational
              sub-CTA copy. */}
          <p className="mt-5 text-xs text-muted-foreground">
            No credit card · 5-minute setup · Connect EODHD or use sample data
          </p>
        </div>

        {/* ── Right column: terminal mock card ──────────────────────────── */}
        {/* WHY a card not a screenshot: ASCII art renders crisp on all DPRs
            and never needs a CDN. The card chrome (window dots + tab strip)
            communicates "this is a terminal", and the live-pulse confirms
            the product is alive. */}
        <div className="relative">
          {/* WHY -inset-2 + blur: subtle amber halo behind the card lifts it
              off the page without resorting to drop-shadow which often looks
              cheap on dark backgrounds. */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-2 rounded-[2px] bg-primary/10 opacity-50 blur-2xl"
          />

          <div className="relative overflow-hidden rounded-[2px] border border-border/60 bg-card shadow-2xl">
            {/* macOS-style window chrome — tells the user "this is an app".
                WHY semantic tokens (not raw HSL): PLAN-0059 token-compliance
                policy forbids raw hex/HSL outside JSON-LD. The dots map to
                destructive/primary/positive which all carry the right
                semantic and visual weight for a window-chrome cue. Fixed in
                PLAN-0052 Wave A QA iter-1 (design audit M1). */}
            <div className="flex items-center gap-2 border-b border-border/50 bg-muted/30 px-3 py-2">
              <div className="flex gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full bg-destructive/70" />
                <span className="h-2.5 w-2.5 rounded-full bg-primary/70" />
                <span className="h-2.5 w-2.5 rounded-full bg-positive/70" />
              </div>
              <span className="ml-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
                worldview · workspace
              </span>
              <span className="ml-auto inline-flex items-center gap-1.5 font-mono text-[9px] text-muted-foreground/50">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-positive opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-positive" />
                </span>
                LIVE
              </span>
            </div>

            {/* ASCII workspace mock */}
            <pre
              aria-label="Worldview terminal workspace preview"
              className="overflow-x-auto whitespace-pre p-4 font-mono text-[11px] leading-[1.6] text-muted-foreground"
            >
              {TERMINAL_LINES.map((line, i) => (
                <span key={i} className="block">
                  {highlight(line)}
                </span>
              ))}
            </pre>

            {/* Status row at the bottom of the terminal — mimics the StatusBar
                in the real product. Ties the marketing visual to the actual UX. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/50 bg-muted/20 px-3 py-2 font-mono text-[10px] text-muted-foreground/80">
              <span>
                <span className="text-positive">●</span> Markets open
              </span>
              <span className="text-border">·</span>
              <span>S&amp;P 5,802.61 +0.34%</span>
              <span className="text-border">·</span>
              <span>VIX 14.82 -3.4%</span>
              <span className="ml-auto">14:32 ET</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/**
 * highlight — split a terminal line into muted box-chars + bright data tokens.
 *
 * WHY THIS HELPER EXISTS: the <pre> uses a single `text-muted-foreground` color;
 * we want numeric data (prices, %, market caps) to render in foreground white
 * so it pops. We can't apply Tailwind classes to substrings inside a string,
 * so we split by regex and wrap matched tokens in a <span>.
 *
 * Patterns matched:
 *   - +1.24% / -0.51% — percent moves with sign
 *   - 189.25 / 28.4x / 6.42 — bare numbers and ratios
 *   - 2.94T — market cap with SI suffix
 *   - HIGH — uppercase severity tokens
 */
function highlight(line: string): React.ReactNode {
  const PATTERN = /([+-]?\d+\.\d+%|[\d,]+\.?\d*[TBM]?|HIGH|LOW|MED)/g;
  const parts: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = PATTERN.exec(line)) !== null) {
    if (m.index > last) parts.push(line.slice(last, m.index));
    const token = m[0];
    // Color positives green, negatives red, severity tags amber, rest white.
    let color = "text-foreground";
    if (token.startsWith("+")) color = "text-positive";
    else if (token.startsWith("-")) color = "text-negative";
    else if (token === "HIGH") color = "text-primary";
    parts.push(
      <span key={m.index} className={color}>
        {token}
      </span>,
    );
    last = m.index + token.length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts.length > 0 ? parts : line;
}
