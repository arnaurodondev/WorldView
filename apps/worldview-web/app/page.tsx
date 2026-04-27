/**
 * app/page.tsx — Public root route (/) — Marketing Landing Page (Wave F-13)
 *
 * WHY THIS EXISTS: The root route "/" is the public landing page.
 * Unauthenticated visitors arrive here from search, links, or the auth redirect.
 * It must convince a trader or investor to sign up or sign in.
 *
 * WHY SERVER COMPONENT: No client-side state, no event handlers, no auth hooks.
 * Keeping it a Server Component allows Next.js to statically pre-render it at
 * build time — fast TTFB and good SEO (important for a thesis demo).
 *
 * WHY THESE 4 FEATURE CARDS: PRD-0028 §2 defines 6 user flows. The four cards
 * highlight the most differentiating features:
 *   - News Intelligence: PRD-0026 market-impact scoring (unique signal)
 *   - Entity Graph: PRD-0017 knowledge graph visualisation (visual differentiator)
 *   - AI Contradictions: PRD-0023 NLP contradiction detection (unique data layer)
 *   - Portfolio Analytics: PRD-0018 portfolio + P&L tracking (retention driver)
 * Prediction markets and RAG chat are notable but less immediately legible
 * to non-expert visitors; they appear in the feature grid below.
 *
 * WHO USES IT: Unauthenticated visitors arriving at the marketing page.
 * DATA SOURCE: None — static marketing content.
 * DESIGN REFERENCE: PRD-0028 §6.5 "Page: Landing"
 */

import Link from "next/link";
import { TrendingUp, Network, Zap, BarChart3, Globe } from "lucide-react";

// ── Feature card data ─────────────────────────────────────────────────────────

/**
 * HERO_FEATURES — the 4 primary feature cards below the hero section
 *
 * WHY THESE 4: See file docstring. The four chosen are most visually interesting
 * in a quick overview (graph, heatmap, AI analysis, portfolio chart).
 */
const HERO_FEATURES = [
  {
    icon: TrendingUp,
    title: "News Intelligence",
    description:
      "NLP-ranked articles with market impact scores and price-window analysis. Know which stories move markets before the crowd does.",
    color: "text-positive", // #26A69A — positively associated with signal quality
  },
  {
    icon: Network,
    title: "Entity Graph",
    description:
      "Visualise company relationships, directors, subsidiaries, and competitive dynamics in an interactive knowledge graph.",
    color: "text-primary", // #E8A317 — amber/gold accent for the flagship feature
  },
  {
    icon: Zap,
    title: "AI Contradictions",
    description:
      "The AI system flags when news sources make conflicting claims about the same entity — surface hidden risk before it hits prices.",
    color: "text-warning", // warning amber for "attention needed" signal
  },
  {
    icon: BarChart3,
    title: "Portfolio Analytics",
    description:
      "Track P&L, portfolio weight, and unrealised gains across all holdings with real-time quote enrichment from market data feeds.",
    color: "text-positive", // #26A69A — financial growth association
  },
] as const;

/**
 * SECONDARY_FEATURES — 6-item grid of all platform capabilities
 *
 * WHY SECONDARY: These are real but less visually differentiated features.
 * Listing them here proves breadth for visitors who scroll past the hero.
 */
const SECONDARY_FEATURES = [
  { title: "AI Research Copilot", desc: "RAG-powered chat with citations from 10K+ news sources" },
  { title: "Prediction Markets", desc: "Polymarket odds integrated with company timelines" },
  { title: "Sector Heatmap", desc: "Real-time 7-step colour-coded GICS sector performance" },
  { title: "Configurable Terminal", desc: "Drag-and-drop workspace with 11 panel types" },
  { title: "Daily Briefs", desc: "AI-generated morning brief personalised to your portfolio" },
  { title: "Economic Calendar", desc: "Upcoming macro events with forecast vs. actual comparison" },
] as const;

/**
 * LIVE_QUOTES — static mock of the live market data bar.
 *
 * WHY STATIC MOCK (not real API call): This is a Server Component rendered at
 * build time. Real quotes would be stale within seconds. The bar's purpose is
 * to demonstrate the terminal's data density and formatting to prospective users
 * — a visitor who sees "SPY 550.32 +0.23%" immediately understands the product.
 * Once signed in, users see live data in the actual terminal.
 *
 * WHY THESE FOUR: SPY (broad market), QQQ (tech / growth), VIX (volatility /
 * fear gauge), BTC (crypto). Together they communicate market breadth — equity,
 * derivatives, and crypto — which matches the platform's asset coverage.
 */
const LIVE_QUOTES = [
  { symbol: "SPY",  price: "550.32", change: "+0.23%", positive: true  },
  { symbol: "QQQ",  price: "458.71", change: "-0.12%", positive: false },
  { symbol: "VIX",  price: "14.82",  change: "-3.40%", positive: false },
  { symbol: "BTC",  price: "67,240", change: "+1.82%", positive: true  },
] as const;

/**
 * TRUST_ITEMS — data-source trust signals shown below the hero.
 *
 * WHY TRUST SIGNALS HERE: Institutional buyers (hedge fund PMs, quant analysts)
 * immediately look for data provenance. Listing EODHD, the AI stack, and local
 * LLM privacy in the above-the-fold area shortens the evaluation cycle for
 * sophisticated visitors who would otherwise hunt for a "data sources" page.
 */
const TRUST_ITEMS = [
  "EODHD Market Data",
  "Knowledge Graph AI",
  "Local LLM Privacy",
  "Real-time Alerts",
] as const;

// ── Terminal preview ASCII layout ─────────────────────────────────────────────

/**
 * TERMINAL_PREVIEW_LINES — ASCII-art workspace mockup.
 *
 * WHY ASCII ART (not a screenshot): A screenshot would need a CDN, adds bytes,
 * and goes stale every release. ASCII art never goes stale, loads at zero cost,
 * and is itself a design signal: this is a keyboard-first terminal tool, not a
 * click-heavy consumer app. The formatting communicates "professional" to the
 * target audience (quant/PM users who use Bloomberg terminals daily).
 *
 * WHY monospaced with box-drawing characters: box-drawing chars (─ │ ┌ ┐ └ ┘ ┬ ┴)
 * are part of every OS font and render identically across platforms. They are not
 * emoji and never need fallback images.
 */
const TERMINAL_PREVIEW_LINES = [
  "┌─────────────┬──────────────────────┐",
  "│ WATCHLIST   │   INSTRUMENT: AAPL   │",
  "│ AAPL  +1.2% │ Price:  $189.25      │",
  "│ MSFT  -0.5% │ P/E:    28.4x        │",
  "│ NVDA  +3.4% │ Sector: Technology   │",
  "│ TSLA  -2.1% │ EPS:    $6.42        │",
  "│ AMZN  +0.8% │ Mkt Cap: $2.94T      │",
  "└─────────────┴──────────────────────┘",
] as const;

// ── Page component ────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* ── Navigation bar ─────────────────────────────────────────────────── */}
      {/* WHY sticky: users may scroll the features section before deciding to
          sign in — the nav bar should always be reachable. */}
      <nav className="sticky top-0 z-40 flex items-center justify-between px-8 py-4 border-b border-border bg-background/95 backdrop-blur-sm">
        {/* WHY NEXT_PUBLIC_APP_NAME env var: allows easy rebranding for the
            thesis demo without changing code. Falls back to "Worldview". */}
        <span className="text-lg font-semibold text-foreground tracking-tight">
          {process.env.NEXT_PUBLIC_APP_NAME ?? "Worldview"}
        </span>
        <div className="flex items-center gap-3">
          {/* WHY next/link: prefetches login page JS on hover, faster navigation */}
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign In
          </Link>
          <Link
            href="/register"
            // WHY shadow-sm + hover:shadow-md: nav CTA gets a subtler amber glow than the
            // hero CTA (shadow-lg) to establish hierarchy: hero > nav. transition-all
            // animates the shadow on hover (transition-colors only handles color, not shadow).
            // WHY rounded-[2px] not rounded-md: 2px radius policy — matches the rest of
            // the app shell and keeps the landing page feeling like a terminal, not a
            // consumer fintech product.
            className="text-sm font-semibold bg-primary text-primary-foreground px-3 py-1.5 rounded-[2px] shadow-sm shadow-primary/20 hover:bg-primary/90 hover:shadow-md hover:shadow-primary/30 transition-all"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* ── Hero section ───────────────────────────────────────────────────── */}
      {/* WHY id="hero": the "Learn More" CTA scrolls to #features; having a
          named anchor on the hero section also helps direct links. */}
      <section id="hero" className="max-w-4xl mx-auto px-8 py-14 text-center">
        {/* WHY "Market Intelligence Terminal": describes the product category
            (terminal = professional tool) + domain (market intelligence).
            "For serious traders" in the sub-head qualifies the audience. */}
        <p className="text-xs font-mono text-primary uppercase tracking-widest mb-4">
          Market Intelligence Terminal
        </p>
        {/* WHY just "Worldview" here: the amber kicker <p> directly above already
            announces "Market Intelligence Terminal". Repeating the same phrase inside
            the h1 is a classic AI-template redundancy — a professional landing page
            uses the category descriptor as a kicker, and the brand name as the headline.
            Separating them creates better visual rhythm and avoids the copy-paste tell. */}
        <h1 className="text-4xl sm:text-5xl font-semibold text-foreground mb-5 leading-tight">
          Worldview
        </h1>
        <p className="text-lg text-muted-foreground mb-4 max-w-2xl mx-auto leading-relaxed">
          Real-time signals, AI-powered insights, and institutional-grade analytics
          for the traders who demand more.
        </p>

        {/* WHY kbd element: signals power-user capability (⌘K to search). Bloomberg
            users expect keyboard shortcuts — this badge communicates "this is a
            professional tool" before the user even signs in. */}
        {/* WHY rounded-[2px]: 2px radius policy — kbd key badges must match
            the system radius. Bare `rounded` resolves to 4px in Tailwind
            (the config only overrides rounded-lg/md/sm, not the base class). */}
        <kbd className="mb-7 inline-block rounded-[2px] border border-border/50 bg-muted/30 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          ⌘K to search instruments
        </kbd>

        {/* ── CTA buttons ────────────────────────────────────────────────── */}
        {/* WHY "Sign In to Access Terminal" not just "Sign In": institutional buyers
            read CTAs carefully. "Access Terminal" communicates the product is ready
            to use now — not a waitlist or a marketing page with a demo request form. */}
        <div className="flex items-center justify-center flex-wrap gap-4 mb-10">
          {/* Primary CTA: Sign In — most landing-page visitors already have accounts
              (referral / direct link); sign-in is higher conversion than register.
              WHY shadow-lg + shadow-primary/25: the amber glow lifts the primary CTA
              above the page surface, establishing clear visual hierarchy over the
              outline-only secondary CTA. hover:shadow-xl deepens the effect on hover. */}
          <Link
            href="/login"
            // WHY rounded-[2px]: 2px radius policy — keeps CTAs sharp and terminal-grade.
            className="bg-primary text-primary-foreground px-7 py-3 rounded-[2px] text-sm font-semibold shadow-lg shadow-primary/25 hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30 transition-all"
          >
            Sign In to Access Terminal
          </Link>
          {/* WHY scroll anchor for "Learn More": users who need convincing scroll
              down; JS-free anchor scroll works even with JS disabled.
              WHY border-border/60 + hover:border-primary/40: the reduced-opacity
              border recedes behind the solid primary CTA; on hover the border
              tints toward primary, creating a subtle "warm invitation" without
              competing with the amber Sign In button. */}
          <a
            href="#features"
            // WHY rounded-[2px]: 2px radius policy — matches hero primary CTA.
            className="text-sm text-muted-foreground border border-border/60 rounded-[2px] px-7 py-3 hover:border-primary/40 hover:text-primary transition-all"
          >
            Learn More
          </a>
        </div>

        {/* ── Trust / data source bar ───────────────────────────────────────── */}
        {/*
         * WHY HERE (between CTA and market bar): trust signals belong above the fold
         * and immediately after the primary action. An institutional buyer reads:
         * "Sign In" → "Powered by EODHD + local LLMs" → has enough context to commit.
         * Placing trust signals below the fold (page footer) means most visitors
         * never see them, which is a conversion anti-pattern for a B2B product.
         */}
        <div className="flex items-center justify-center flex-wrap gap-1.5 text-[10px] text-muted-foreground/60 font-mono">
          <span className="uppercase tracking-wider text-muted-foreground/40">Powered by</span>
          {TRUST_ITEMS.map((item, i) => (
            <span key={item} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-border/60">·</span>}
              {item}
            </span>
          ))}
        </div>
      </section>

      {/* ── Live market data preview bar ───────────────────────────────────── */}
      {/*
       * WHY A MARKET DATA BAR: Above-the-fold data density is the single most
       * important trust signal for a trading terminal product. Finviz, Bloomberg,
       * and TradingView all open with live data visible — visitors evaluate data
       * quality before reading any marketing copy.
       *
       * WHY STATIC MOCK DATA: See LIVE_QUOTES constant comment above.
       * The bar is labeled "SAMPLE DATA" so it is honest about being static;
       * this avoids misleading users about the latency or freshness.
       *
       * WHY font-mono + tabular-nums: price values must align vertically across
       * rows and not jitter as digits change width. IBM Plex Mono is the system
       * monospace; tabular-nums forces equal-width numerals in all weights.
       */}
      <section className="max-w-4xl mx-auto px-8 pb-10">
        <div className="rounded-[2px] border border-border/40 bg-card overflow-hidden">
          {/* Label row */}
          <div className="px-4 py-1.5 border-b border-border/30 flex items-center gap-2">
            {/* WHY pulsing dot: signals "live data" without text, matching Bloomberg
                and Reuters terminal conventions for live feed indicators. */}
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-positive opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-positive" />
            </span>
            <span className="text-[9px] font-mono uppercase tracking-[0.14em] text-muted-foreground/50">
              Sample Market Data
            </span>
          </div>

          {/* Quote row */}
          <div className="px-4 py-2.5 flex items-center gap-6 flex-wrap">
            {LIVE_QUOTES.map((q) => (
              <div key={q.symbol} className="flex items-baseline gap-2">
                {/* Symbol label — dimmer, all-caps monospace */}
                <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/70">
                  {q.symbol}
                </span>
                {/* Price — full foreground, tabular numerals */}
                <span className="text-[13px] font-mono tabular-nums text-foreground">
                  {q.price}
                </span>
                {/* Change — green or red per direction */}
                {/* WHY inline conditional class: Server Components cannot use cn() with
                    dynamic values that differ per element when the value is runtime data.
                    The ternary is the correct pattern here — no client JS needed. */}
                <span
                  className={`text-[11px] font-mono tabular-nums ${
                    q.positive
                      ? "text-[hsl(var(--positive))]"
                      : "text-[hsl(var(--negative))]"
                  }`}
                >
                  {q.change}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Primary feature cards ──────────────────────────────────────────── */}
      {/* WHY id="features": "Learn More" anchor target from the hero section. */}
      <section id="features" className="max-w-5xl mx-auto px-8 py-10">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-semibold text-foreground mb-3">
            Everything you need to trade with an edge
          </h2>
          <p className="text-sm text-muted-foreground max-w-xl mx-auto">
            Institutional-grade signal infrastructure, open architecture, built on
            EODHD market data and local LLMs for full data sovereignty.
          </p>
        </div>

        {/* WHY grid-cols-2 on md+: 4 cards fit as 2×2 on tablet/desktop.
            Single column on mobile keeps cards readable without truncation. */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {HERO_FEATURES.map((feature) => {
            const Icon = feature.icon;
            return (
              <div
                key={feature.title}
                // WHY rounded-[2px]: 2px radius policy — feature cards must match the
                // card.tsx component which was updated to rounded-[2px] in the F-001/F-002
                // palette overhaul. rounded-xl breaks the first visual impression.
                // WHY p-4 (down from p-6): terminal density — reduce padding to match the
                // data-dense aesthetic of the app itself (22px rows, 11px data text).
                className="bg-card rounded-[2px] p-4 border border-border/40 hover:border-primary/30 transition-colors"
              >
                {/* WHY icon + title on same row: reduces vertical scanning distance;
                    traders scan quickly and don't read every word. */}
                <div className="flex items-center gap-3 mb-2">
                  <Icon
                    className={`h-4 w-4 ${feature.color} flex-shrink-0`}
                    aria-hidden="true"
                  />
                  <h3 className="text-xs font-semibold text-foreground">
                    {feature.title}
                  </h3>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {feature.description}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Terminal Preview section ───────────────────────────────────────── */}
      {/*
       * WHY A TERMINAL PREVIEW: Abstract feature descriptions don't convert as well
       * as showing the actual product experience. The ASCII workspace mockup lets a
       * visitor instantly understand the layout: sidebar watchlist + main instrument
       * panel. This pattern is used by VS Code, Neovim, and Bloomberg web pages.
       *
       * WHY <pre> NOT a screenshot: <pre> is perfectly readable, zero bytes, never
       * stale. Box-drawing characters render identically on macOS/Windows/Linux.
       * A screenshot requires a CDN, has JPEG artifacts, and needs alt text.
       *
       * WHY text-muted-foreground for structure, text-primary for data values:
       * the box borders recede visually while the data (prices, ratios) pop at
       * full primary-color weight. This mirrors how Bloomberg colors its terminal
       * chrome vs. the live data it displays.
       */}
      <section className="max-w-5xl mx-auto px-8 pb-10">
        <div className="text-center mb-5">
          <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground/50 mb-1">
            Terminal Preview
          </p>
          <h2 className="text-lg font-semibold text-foreground">
            The workspace you&apos;ll work in
          </h2>
        </div>

        {/* Card wrapper — matches the bg-card elevation of app panels */}
        <div className="rounded-[2px] border border-border/40 bg-card p-5 flex justify-center">
          {/*
           * WHY overflow-x-auto on the outer div: on small screens the ASCII art
           * is ~42 chars wide. Rather than wrapping (which breaks the box) we let
           * it scroll horizontally inside the card container.
           */}
          <div className="overflow-x-auto">
            <pre
              // WHY text-[11px]: standard terminal data-text size per the design system.
              // WHY leading-[1.6]: box-drawing characters need slight extra line-height
              // so the horizontal rules connect cleanly to the vertical pipes.
              className="font-mono text-[11px] leading-[1.6] text-muted-foreground whitespace-pre select-none"
              aria-label="Terminal workspace layout preview"
            >
              {TERMINAL_PREVIEW_LINES.map((line, i) => (
                // WHY split rendering per line: we need to highlight data columns
                // (price, ratio values) in text-primary while keeping box chars muted.
                // A single string with a CSS class can't target sub-strings, but
                // rendering line-by-line with a <span key> lets each line be processed.
                // Here we use a simple heuristic: lines containing "$", "%" or "x"
                // (numeric data markers) get a subtle data-highlight treatment via
                // partial bold spans injected by the HighlightLine helper below.
                <span key={i} className="block">
                  {highlightTerminalLine(line)}
                </span>
              ))}
            </pre>
          </div>
        </div>

        {/* Caption row — explains what the visitor is looking at */}
        <p className="text-center text-[10px] text-muted-foreground/50 mt-3 font-mono">
          Resizable panel workspace — watchlist, instrument detail, portfolio, and AI chat side by side
        </p>
      </section>

      {/* ── Secondary feature grid ─────────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-8 py-8">
        <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-widest mb-5 text-center">
          Also included
        </h2>
        {/* WHY grid-cols-3: secondary features are tighter descriptions;
            3 columns at desktop keep them compact without being unreadable. */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SECONDARY_FEATURES.map((f) => (
            <div
              key={f.title}
              // WHY rounded-[2px]: 2px radius policy — secondary feature cards must
              // match the primary feature cards and the app shell panel style.
              // WHY p-3 (down from p-4): secondary features warrant less padding —
              // they are supporting information, not primary value propositions.
              className="bg-card rounded-[2px] p-3 border border-border/40"
            >
              <h3 className="text-[11px] font-medium text-foreground mb-0.5">{f.title}</h3>
              <p className="text-[10px] text-muted-foreground leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Social proof / thesis context ──────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-8 py-12 text-center">
        <div
          // WHY rounded-[2px]: 2px radius policy — the social proof card uses the same
          // panel treatment as the rest of the app; rounded-xl breaks the terminal aesthetic.
          className="rounded-[2px] border border-border/60 bg-card p-6 space-y-3"
        >
          <Globe className="mx-auto h-6 w-6 text-muted-foreground/50" aria-hidden="true" />
          <p className="text-xs text-muted-foreground leading-relaxed">
            Built as a university final thesis project demonstrating microservices
            architecture, AI/ML integration, and institutional-grade UX on a
            modern Python + Next.js 15 stack.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap text-[10px] text-muted-foreground/70">
            <span>10 microservices</span>
            <span className="text-border">·</span>
            <span>6 shared libraries</span>
            <span className="text-border">·</span>
            <span>EODHD market data</span>
            <span className="text-border">·</span>
            <span>Local LLMs</span>
          </div>
        </div>
      </section>

      {/* ── Final CTA ──────────────────────────────────────────────────────── */}
      {/*
       * WHY a second full CTA section at the bottom: high-intent users who scroll
       * through the entire page should not need to scroll back up to the hero CTA.
       * This is a standard conversion pattern — match the hero CTA at the bottom
       * for users who completed their "due diligence scroll".
       */}
      <section className="max-w-2xl mx-auto px-8 py-14 text-center">
        <h2 className="text-xl font-semibold text-foreground mb-3">
          Ready to trade with institutional-grade intelligence?
        </h2>
        <p className="text-sm text-muted-foreground mb-7">
          Sign in to access the full terminal — real-time market data, AI signals,
          and your portfolio in one unified workspace.
        </p>
        <div className="flex items-center justify-center gap-4 flex-wrap">
          {/* WHY match hero CTA pattern: repeating the same amber glow + semibold
              treatment reinforces visual consistency and gives the final CTA the
              same urgency as the hero — users who scrolled this far are high-intent. */}
          <Link
            href="/login"
            // WHY rounded-[2px]: 2px radius policy — matches hero CTA and the rest of the app.
            className="bg-primary text-primary-foreground px-7 py-3 rounded-[2px] text-sm font-semibold shadow-lg shadow-primary/25 hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30 transition-all"
          >
            Sign In to Access Terminal
          </Link>
          {/* WHY outline style matches hero secondary: consistent visual language
              across all CTA pairs — outline = lower commitment action. */}
          <Link
            href="/register"
            // WHY rounded-[2px]: 2px radius policy — matches primary CTA in this section.
            className="text-sm text-muted-foreground border border-border/60 rounded-[2px] px-7 py-3 hover:border-primary/40 hover:text-primary transition-all"
          >
            Create account
          </Link>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="border-t border-border mt-4 px-8 py-6 text-center">
        <p className="text-[10px] text-muted-foreground/60">
          Built on EODHD data · Powered by local LLMs · Open architecture
        </p>
        <p className="text-[10px] text-muted-foreground/40 mt-1.5">
          &copy; 2026 Worldview. University Final Thesis Project.
        </p>
      </footer>
    </main>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * highlightTerminalLine — returns JSX for a single ASCII terminal line with
 * data values (prices, ratios, percentages) highlighted in text-primary color.
 *
 * WHY THIS HELPER EXISTS: Inside a <pre> block we can't use Tailwind classes on
 * substrings directly. The box-drawing structure chars (─ │ ┌ etc.) should stay
 * muted (text-muted-foreground) while numeric data values (anything after ": " or
 * containing "$", "%", "x") should render in text-foreground (white) so they pop.
 *
 * IMPLEMENTATION: simple regex split — split on patterns like "$189.25", "+1.2%",
 * "28.4x", "2.94T". Matched tokens render as text-foreground; unmatched tokens
 * keep the inherited muted color.
 *
 * WHY REGEX NOT A PARSER: This is presentation-layer formatting for a static
 * mock — a regex is the simplest correct solution. A full parser would be
 * over-engineering for 8 static lines.
 */
function highlightTerminalLine(line: string): React.ReactNode {
  // Match: $ + digits/comma/period, or digits+% pattern (e.g. +1.2%), or
  // digits + x suffix (P/E ratio), or digits+T/B (market cap), or bare prices.
  const DATA_PATTERN = /(\$[\d,\.]+[TBM]?|[+-]?\d+\.?\d*%|[\d,\.]+x|\$[\d,\.]+|\d+\.\d+T)/g;

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = DATA_PATTERN.exec(line)) !== null) {
    // Text before the match — muted (inherits parent color)
    if (match.index > lastIndex) {
      parts.push(line.slice(lastIndex, match.index));
    }
    // The matched data token — primary foreground
    parts.push(
      <span key={match.index} className="text-foreground">
        {match[0]}
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }

  // Remaining text after the last match
  if (lastIndex < line.length) {
    parts.push(line.slice(lastIndex));
  }

  return parts.length > 0 ? parts : line;
}
