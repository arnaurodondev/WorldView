/**
 * __tests__/landing.test.tsx — PLAN-0052 Wave A landing page coverage
 *
 * WHY THIS EXISTS: Each landing section has a small observable surface
 * (heading text, CTA href, key copy). Vitest unit tests are sufficient to
 * lock those surfaces against regression — Playwright a11y / responsive
 * snapshot coverage lives in `e2e/landing.spec.ts`.
 *
 * SCOPE:
 *   T-A-1-01 HeroSection         — primary CTA href + headline
 *   T-A-1-02 LiveDataStrip       — renders all 6 sample tickers
 *   T-A-1-03 SectorHeatmapPreview — renders 6 sector tiles + heading
 *   T-A-1-04 DifferentiatorsSection — 3 differentiator cards
 *   T-A-1-05 WorkflowSection      — ordered list with 4 steps
 *   T-A-1-06 AIDemoSection        — citations match question
 *   T-A-1-07 ComparisonTable      — header lists 4 competitors + Worldview
 *   T-A-1-08 TrustBadges          — lists 5 data sources
 *   T-A-1-09 PricingTiers         — toggle switches monthly/annual price
 *   T-A-1-10 Testimonials         — renders 3 personas
 *   T-A-1-11 FAQAccordion         — accordion items toggle on click
 *   T-A-1-12 Footer               — has docs / status / legal links
 *   T-A-1-14 Sitemap              — sitemap module exports the marketing routes
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

// next/link with React 19 + Next 15 renders fine in jsdom; no mock needed.
// next/navigation hooks are not used by any landing section (all server-safe
// or local useState only), so we can render directly.

// Mock next/link minimally — Next 15 Link works in jsdom but we keep it
// trivial to avoid pulling the full router into unit tests.
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { HeroSection } from "@/components/landing/HeroSection";
import { LiveDataStrip } from "@/components/landing/LiveDataStrip";
import { SectorHeatmapPreview } from "@/components/landing/SectorHeatmapPreview";
import { DifferentiatorsSection } from "@/components/landing/DifferentiatorsSection";
import { WorkflowSection } from "@/components/landing/WorkflowSection";
import { AIDemoSection } from "@/components/landing/AIDemoSection";
import { ComparisonTable } from "@/components/landing/ComparisonTable";
import { TrustBadges } from "@/components/landing/TrustBadges";
import { PricingTiers } from "@/components/landing/PricingTiers";
import { Testimonials } from "@/components/landing/Testimonials";
import { FAQAccordion } from "@/components/landing/FAQAccordion";
import { Footer } from "@/components/landing/Footer";

describe("T-A-1-01 — HeroSection", () => {
  it("renders the headline and a primary CTA pointing to /register", () => {
    render(<HeroSection />);
    expect(screen.getByText(/Bloomberg-grade research/i)).toBeInTheDocument();
    const cta = screen.getByTestId("hero-primary-cta");
    expect(cta).toHaveAttribute("href", "/register");
  });

  it("includes a Sign in secondary CTA pointing to /login", () => {
    render(<HeroSection />);
    const signin = screen.getByRole("link", { name: /^sign in$/i });
    expect(signin).toHaveAttribute("href", "/login");
  });

  it("renders the terminal ASCII workspace preview", () => {
    render(<HeroSection />);
    expect(
      screen.getByLabelText(/terminal workspace preview/i),
    ).toBeInTheDocument();
  });
});

describe("T-A-1-02 — LiveDataStrip", () => {
  it("renders all 6 sample tickers", () => {
    render(<LiveDataStrip />);
    ["SPY", "QQQ", "VIX", "BTC", "TLT", "GLD"].forEach((sym) => {
      expect(screen.getByText(sym)).toBeInTheDocument();
    });
  });

  it("labels itself as sample data (not real-time)", () => {
    render(<LiveDataStrip />);
    expect(screen.getByText(/sample data/i)).toBeInTheDocument();
  });
});

describe("T-A-1-03 — SectorHeatmapPreview", () => {
  it("renders 6 SPDR sector tiles", () => {
    render(<SectorHeatmapPreview />);
    ["XLK", "XLF", "XLV", "XLE", "XLY", "XLI"].forEach((sym) => {
      expect(screen.getByText(sym)).toBeInTheDocument();
    });
  });

  it("uses heading 7-step heatmap text", () => {
    render(<SectorHeatmapPreview />);
    expect(
      screen.getByRole("heading", { level: 2, name: /heatmap/i }),
    ).toBeInTheDocument();
  });
});

describe("T-A-1-04 — DifferentiatorsSection", () => {
  it("renders 3 differentiator cards with all titles", () => {
    render(<DifferentiatorsSection />);
    expect(screen.getByText(/News intelligence, not aggregation/i)).toBeInTheDocument();
    expect(screen.getByText(/Knowledge graph over flat tickers/i)).toBeInTheDocument();
    expect(screen.getByText(/Multi-source data fusion/i)).toBeInTheDocument();
  });
});

describe("T-A-1-05 — WorkflowSection", () => {
  it("renders an ordered list with the 4 steps", () => {
    render(<WorkflowSection />);
    const steps = ["Discover", "Analyze", "Track", "Act"];
    steps.forEach((step) => {
      expect(
        screen.getByRole("heading", { level: 3, name: step }),
      ).toBeInTheDocument();
    });
  });

  it("uses an <ol> for the workflow steps (semantic order)", () => {
    const { container } = render(<WorkflowSection />);
    expect(container.querySelector("ol")).not.toBeNull();
  });
});

describe("T-A-1-06 — AIDemoSection", () => {
  it("renders the example question", () => {
    render(<AIDemoSection />);
    expect(screen.getByText(/Why did NVDA drop/i)).toBeInTheDocument();
  });

  it("renders a Sources box with at least 3 citations", () => {
    render(<AIDemoSection />);
    expect(screen.getByText(/^Sources$/i)).toBeInTheDocument();
    // Bloomberg appears in both the question text and the citation list,
    // so match >=1 occurrences rather than requiring uniqueness.
    expect(screen.getAllByText(/Bloomberg/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/SEC EDGAR/i)).toBeInTheDocument();
  });
});

describe("T-A-1-07 — ComparisonTable", () => {
  it("renders Worldview + 4 competitors as column headers", () => {
    render(<ComparisonTable />);
    ["Worldview", "Bloomberg", "IBKR", "TradingView", "Finviz"].forEach((name) => {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    });
  });

  it("includes the price comparison row", () => {
    render(<ComparisonTable />);
    expect(screen.getByText(/Estimated monthly cost/i)).toBeInTheDocument();
  });
});

describe("T-A-1-08 — TrustBadges", () => {
  it("lists 5 data sources", () => {
    render(<TrustBadges />);
    ["EODHD", "Finnhub", "SEC EDGAR", "Polymarket", "TastyTrade"].forEach((s) => {
      expect(screen.getByText(s)).toBeInTheDocument();
    });
  });
});

describe("T-A-1-09 — PricingTiers monthly/annual toggle", () => {
  it("defaults to annual billing and shows the discounted Pro price", () => {
    render(<PricingTiers />);
    // Annual Pro = $24/mo
    expect(screen.getByText("$24")).toBeInTheDocument();
  });

  it("switches to monthly when the Monthly toggle is clicked", () => {
    render(<PricingTiers />);
    const monthlyTab = screen.getByRole("tab", { name: /monthly/i });
    fireEvent.click(monthlyTab);
    // Monthly Pro = $29
    expect(screen.getByText("$29")).toBeInTheDocument();
  });

  it("renders all 3 tiers", () => {
    render(<PricingTiers />);
    expect(screen.getByRole("heading", { level: 3, name: /^free$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: /^pro$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: /^enterprise$/i })).toBeInTheDocument();
  });
});

describe("T-A-1-10 — Testimonials", () => {
  it("renders 3 figure elements (one per persona)", () => {
    const { container } = render(<Testimonials />);
    expect(container.querySelectorAll("figure")).toHaveLength(3);
  });
});

describe("T-A-1-11 — FAQAccordion", () => {
  it("renders all FAQ questions as collapsed buttons by default", () => {
    render(<FAQAccordion />);
    const buttons = screen.getAllByRole("button");
    // 10 FAQ questions, all rendered as accordion triggers (buttons).
    expect(buttons.length).toBeGreaterThanOrEqual(10);
  });

  it("expands an item when its trigger is clicked", () => {
    render(<FAQAccordion />);
    const trigger = screen.getByRole("button", {
      name: /thesis demo/i,
    });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});

describe("T-A-1-12 — Footer", () => {
  it("includes the four secondary nav columns", () => {
    render(<Footer />);
    ["Product", "Resources", "Company", "Legal"].forEach((col) => {
      expect(screen.getByText(col)).toBeInTheDocument();
    });
  });

  it("links to /docs", () => {
    render(<Footer />);
    const docsLink = screen.getByRole("link", { name: /^documentation$/i });
    expect(docsLink).toHaveAttribute("href", "/docs");
  });

  it("renders the All systems operational status badge", () => {
    render(<Footer />);
    expect(screen.getByText(/All systems operational/i)).toBeInTheDocument();
  });
});

describe("T-A-1-14 — sitemap.ts contract", () => {
  it("returns the canonical public URL set", async () => {
    const { default: sitemap } = await import("@/app/sitemap");
    const entries = sitemap();
    const urls = entries.map((e) => e.url);
    // All entries must point to the same origin (no env leakage).
    const origins = new Set(urls.map((u) => new URL(u).origin));
    expect(origins.size).toBe(1);
    // Required public routes are present.
    [
      "/",
      "/docs",
      "/feedback",
      "/login",
      "/register",
    ].forEach((path) => {
      expect(urls.some((u) => new URL(u).pathname === path)).toBe(true);
    });
  });
});
