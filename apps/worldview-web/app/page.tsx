/**
 * app/page.tsx — Public root route (/)
 *
 * WHY THIS EXISTS: The root route "/" is the public landing page.
 * It is a Server Component (no "use client") because it's pure markup.
 * The FAQ section is handled by a client component for accordion state.
 *
 * This is the F-1 Bootstrap placeholder. The full landing page will be
 * implemented in Wave F-13 (Settings + Landing page).
 *
 * WHO USES IT: Unauthenticated visitors arriving at the marketing page.
 * DATA SOURCE: None — static marketing content.
 * DESIGN REFERENCE: PRD-0028 §6.5 Page: Landing
 */

import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* Navigation */}
      <nav className="flex items-center justify-between px-8 py-4 border-b border-border">
        <span className="text-lg font-semibold text-foreground tracking-tight">
          {process.env.NEXT_PUBLIC_APP_NAME ?? "Worldview"}
        </span>
        <div className="flex items-center gap-3">
          {/* WHY next/link: prefetches login page JS on hover, faster navigation */}
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Log in
          </Link>
          <Link
            href="/register"
            className="text-sm bg-primary text-primary-foreground px-3 py-1.5 rounded-md hover:bg-primary/90 transition-colors"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-8 py-24 text-center">
        <h1 className="text-4xl font-semibold text-foreground mb-4 leading-tight">
          The Intelligence Terminal for Modern Investors
        </h1>
        <p className="text-lg text-muted-foreground mb-8 max-w-2xl mx-auto">
          Bloomberg-grade market intelligence — AI research copilot, entity knowledge
          graphs, news intelligence, prediction markets — at $29/month.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/register"
            className="bg-primary text-primary-foreground px-6 py-2.5 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Get started free
          </Link>
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in →
          </Link>
        </div>
      </section>

      {/* Feature highlights — placeholder for F-13 full implementation */}
      <section className="max-w-5xl mx-auto px-8 py-12 grid grid-cols-3 gap-6">
        {[
          { title: "AI Research Copilot", desc: "RAG-powered chat with citations from 10K+ news sources" },
          { title: "Entity Knowledge Graph", desc: "Visualise company relationships, directors, subsidiaries, and events" },
          { title: "News Intelligence", desc: "NLP-scored articles with market impact prediction" },
          { title: "Prediction Markets", desc: "Polymarket odds integrated with company timelines" },
          { title: "Configurable Terminal", desc: "Drag-and-drop workspace with 8 panel types" },
          { title: "Daily Briefs", desc: "AI-generated morning brief personalised to your portfolio" },
        ].map((f) => (
          <div key={f.title} className="bg-card rounded-lg p-5 border border-border">
            <h3 className="text-sm font-medium text-foreground mb-2">{f.title}</h3>
            <p className="text-xs text-muted-foreground leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </section>

      {/* Footer */}
      <footer className="border-t border-border mt-16 px-8 py-8 text-center">
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
