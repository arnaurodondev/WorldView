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
    color: "text-primary", // #0EA5E9 — primary brand colour for the flagship feature
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
            className="text-sm bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* ── Hero section ───────────────────────────────────────────────────── */}
      {/* WHY id="hero": the "Learn More" CTA scrolls to #features; having a
          named anchor on the hero section also helps direct links. */}
      <section id="hero" className="max-w-4xl mx-auto px-8 py-28 text-center">
        {/* WHY "Market Intelligence Terminal": describes the product category
            (terminal = professional tool) + domain (market intelligence).
            "For serious traders" in the sub-head qualifies the audience. */}
        <p className="text-xs font-mono text-primary uppercase tracking-widest mb-4">
          Market Intelligence Terminal
        </p>
        <h1 className="text-4xl sm:text-5xl font-semibold text-foreground mb-6 leading-tight">
          Worldview — Market Intelligence Terminal
        </h1>
        <p className="text-lg text-muted-foreground mb-10 max-w-2xl mx-auto leading-relaxed">
          Real-time signals, AI-powered insights, and institutional-grade analytics
          for serious traders. Bloomberg-grade terminal at a fraction of the cost.
        </p>

        {/* ── CTA buttons ────────────────────────────────────────────────── */}
        <div className="flex items-center justify-center flex-wrap gap-4">
          {/* Primary CTA: Sign In — most landing-page visitors already have accounts
              (referral / direct link); sign-in is higher conversion than register. */}
          <Link
            href="/login"
            className="bg-primary text-primary-foreground px-7 py-3 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Sign In
          </Link>
          {/* WHY scroll anchor for "Learn More": users who need convincing scroll
              down; JS-free anchor scroll works even with JS disabled. */}
          <a
            href="#features"
            className="text-sm text-muted-foreground border border-border rounded-md px-7 py-3 hover:text-foreground hover:border-border/80 transition-colors"
          >
            Learn More ↓
          </a>
        </div>
      </section>

      {/* ── Primary feature cards ──────────────────────────────────────────── */}
      {/* WHY id="features": "Learn More" anchor target from the hero section. */}
      <section id="features" className="max-w-5xl mx-auto px-8 py-16">
        <div className="text-center mb-10">
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
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          {HERO_FEATURES.map((feature) => {
            const Icon = feature.icon;
            return (
              <div
                key={feature.title}
                className="bg-card rounded-xl p-6 border border-border/60 hover:border-border transition-colors"
              >
                {/* WHY icon + title on same row: reduces vertical scanning distance;
                    traders scan quickly and don't read every word. */}
                <div className="flex items-center gap-3 mb-3">
                  <Icon
                    className={`h-5 w-5 ${feature.color} flex-shrink-0`}
                    aria-hidden="true"
                  />
                  <h3 className="text-sm font-semibold text-foreground">
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

      {/* ── Secondary feature grid ─────────────────────────────────────────── */}
      <section className="max-w-5xl mx-auto px-8 py-12">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-widest mb-6 text-center">
          Also included
        </h2>
        {/* WHY grid-cols-3: secondary features are tighter descriptions;
            3 columns at desktop keep them compact without being unreadable. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECONDARY_FEATURES.map((f) => (
            <div key={f.title} className="bg-card rounded-lg p-4 border border-border/40">
              <h3 className="text-xs font-medium text-foreground mb-1">{f.title}</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Social proof / thesis context ──────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-8 py-16 text-center">
        <div className="rounded-xl border border-border/60 bg-card p-8 space-y-4">
          <Globe className="mx-auto h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
          <p className="text-sm text-muted-foreground leading-relaxed">
            Built as a university final thesis project demonstrating microservices
            architecture, AI/ML integration, and institutional-grade UX on a
            modern Python + Next.js 15 stack.
          </p>
          <div className="flex items-center justify-center gap-4 flex-wrap text-xs text-muted-foreground/70">
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
      <section className="max-w-2xl mx-auto px-8 py-16 text-center">
        <h2 className="text-2xl font-semibold text-foreground mb-4">
          Ready to start?
        </h2>
        <p className="text-sm text-muted-foreground mb-8">
          Sign in to access the full terminal — real-time market data, AI signals,
          and your portfolio in one unified workspace.
        </p>
        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link
            href="/login"
            className="bg-primary text-primary-foreground px-7 py-3 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Sign In
          </Link>
          <Link
            href="/register"
            className="text-sm text-muted-foreground border border-border rounded-md px-7 py-3 hover:text-foreground hover:border-border/80 transition-colors"
          >
            Create account
          </Link>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="border-t border-border mt-8 px-8 py-8 text-center">
        <p className="text-xs text-muted-foreground">
          Built on EODHD data · Powered by local LLMs · Open architecture
        </p>
        <p className="text-xs text-muted-foreground mt-2">
          © 2026 Worldview. University Final Thesis Project.
        </p>
      </footer>
    </main>
  );
}
