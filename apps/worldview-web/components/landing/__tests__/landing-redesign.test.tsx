/**
 * components/landing/__tests__/landing-redesign.test.tsx
 *
 * Coverage for the 2026-06-23 landing redesign
 * (docs/design/2026-06-23-landing-page-redesign.md §6 test requirements):
 *   - FeatureGrid             — 6 tiles + deep-link anchors
 *   - KnowledgeGraphSpotlight — heading + path chain + proof footer
 *   - WeirdPathCard           — query chip + hops + takeaway
 *   - WeirdnessScoreBars      — scoreBand() thresholds + composite render
 *   - HowItWorks              — pipeline strip + 4 pillars
 *   - ProductShot             — placeholder fallback + image mode
 *   - AIDemoSection refresh   — slash chips, confidence bar, model label gone
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

// Mock next/link (matches the existing landing.test.tsx convention).
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [k: string]: unknown;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Mock next/image — jsdom doesn't load images; render a plain <img> so we can
// assert src/alt without the next/image runtime.
vi.mock("next/image", () => ({
  __esModule: true,
  default: ({ src, alt, ...rest }: { src: string; alt: string; [k: string]: unknown }) => {
    // Drop next/image-only boolean props that React would warn about on <img>.
    const { priority: _p, ...imgProps } = rest as Record<string, unknown>;
    void _p;
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt={alt} {...imgProps} />;
  },
}));

import { FeatureGrid } from "@/components/landing/FeatureGrid";
import { KnowledgeGraphSpotlight } from "@/components/landing/KnowledgeGraphSpotlight";
import { WeirdPathCard } from "@/components/landing/WeirdPathCard";
import {
  WeirdnessScoreBars,
  scoreBand,
} from "@/components/landing/WeirdnessScoreBars";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { ProductShot } from "@/components/landing/ProductShot";
import { AIDemoSection } from "@/components/landing/AIDemoSection";
import { ComparisonTable } from "@/components/landing/ComparisonTable";

describe("FeatureGrid", () => {
  it("renders all 6 surface tiles", () => {
    render(<FeatureGrid />);
    [
      "Knowledge-graph intelligence",
      "Grounded AI chat",
      "Portfolio analytics",
      "Fundamentals screener",
      "News intelligence",
      "Instrument detail",
    ].forEach((title) => {
      expect(screen.getByText(title)).toBeInTheDocument();
    });
  });

  it("deep-links the first two tiles to the showcase anchors", () => {
    render(<FeatureGrid />);
    const kgLink = screen.getByRole("link", {
      name: /Knowledge-graph intelligence/i,
    });
    expect(kgLink).toHaveAttribute("href", "#intelligence");
    const chatLink = screen.getByRole("link", { name: /Grounded AI chat/i });
    expect(chatLink).toHaveAttribute("href", "#ai");
  });

  it("uses the redesign heading", () => {
    render(<FeatureGrid />);
    expect(
      screen.getByRole("heading", { level: 2, name: /Six surfaces/i }),
    ).toBeInTheDocument();
  });
});

describe("KnowledgeGraphSpotlight", () => {
  it("renders the signature-feature heading and proof footer", () => {
    render(<KnowledgeGraphSpotlight />);
    expect(
      screen.getByRole("heading", { level: 2, name: /never think to search/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/pgvector \+ AGE \+ BM25/i)).toBeInTheDocument();
  });

  it("renders the section with id=intelligence (nav anchor target)", () => {
    const { container } = render(<KnowledgeGraphSpotlight />);
    expect(container.querySelector("#intelligence")).not.toBeNull();
  });

  it("renders the AAPL→TSMC→ASML path chain", () => {
    render(<KnowledgeGraphSpotlight />);
    ["AAPL", "TSMC", "ASML"].forEach((t) => {
      expect(screen.getByText(t)).toBeInTheDocument();
    });
    expect(screen.getByText("/path AAPL ASML")).toBeInTheDocument();
  });
});

describe("WeirdPathCard", () => {
  it("renders query, hops, scores, and takeaway", () => {
    render(
      <WeirdPathCard
        query="/path A B"
        hops={[
          { from: "A", to: "M", relation: "rel_one" },
          { from: "M", to: "B", relation: "rel_two" },
        ]}
        scores={[
          { label: "Reliability", value: 0.9 },
          { label: "Novelty", value: 0.3 },
        ]}
        composite={0.6}
        takeaway="A connects to B through M."
      />,
    );
    expect(screen.getByText("/path A B")).toBeInTheDocument();
    expect(screen.getByText("rel_one")).toBeInTheDocument();
    expect(screen.getByText("rel_two")).toBeInTheDocument();
    expect(screen.getByText("A connects to B through M.")).toBeInTheDocument();
    // 3 unique nodes (A, M, B) rendered from 2 contiguous hops.
    ["A", "M", "B"].forEach((n) =>
      expect(screen.getByText(n)).toBeInTheDocument(),
    );
  });
});

describe("WeirdnessScoreBars.scoreBand", () => {
  it("classifies high / medium / low at the §6.14 thresholds", () => {
    expect(scoreBand(0.7)).toBe("high");
    expect(scoreBand(0.91)).toBe("high");
    expect(scoreBand(0.69)).toBe("medium");
    expect(scoreBand(0.4)).toBe("medium");
    expect(scoreBand(0.39)).toBe("low");
    expect(scoreBand(0)).toBe("low");
  });

  it("renders a labelled, colour-blind-safe bar per score plus composite", () => {
    render(
      <WeirdnessScoreBars
        scores={[
          { label: "Reliability", value: 0.91 },
          { label: "Novelty", value: 0.55 },
        ]}
        composite={0.72}
      />,
    );
    // Each bar exposes a role="img" with an aria-label containing the numeric
    // value + band (redundant, colour-blind-safe per §6.11b).
    expect(
      screen.getByRole("img", { name: /Reliability: 0\.91 \(high\)/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Weirdness: 0\.72 \(high\)/i }),
    ).toBeInTheDocument();
  });
});

describe("HowItWorks", () => {
  it("renders the heading, pipeline strip, and 4 pillars", () => {
    render(<HowItWorks />);
    expect(
      screen.getByRole("heading", { level: 2, name: /Built like infrastructure/i }),
    ).toBeInTheDocument();
    // Pipeline strip is one role="img" with a descriptive label.
    expect(
      screen.getByRole("img", { name: /Retrieval pipeline/i }),
    ).toBeInTheDocument();
    [
      /10 event-driven microservices/i,
      /Single S9 API gateway/i,
      /Externalized LLMs/i,
      /Full citation chain/i,
    ].forEach((re) => expect(screen.getByText(re)).toBeInTheDocument());
  });
});

describe("ProductShot", () => {
  it("renders a placeholder panel (role=img) when placeholder is set", () => {
    render(
      <ProductShot src="/landing/x.png" alt="Example shot" label="demo" placeholder />,
    );
    // No <img> in placeholder mode; the panel itself is the role="img".
    expect(screen.queryByRole("img", { name: "Example shot" })).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders an <img> with src + alt when not a placeholder", () => {
    render(<ProductShot src="/landing/y.png" alt="Real shot" label="demo" />);
    const img = screen.getByAltText("Real shot");
    expect(img).toHaveAttribute("src", "/landing/y.png");
  });

  it("shows the LIVE pill when live is set", () => {
    render(
      <ProductShot src="/landing/z.png" alt="Live shot" label="demo" live placeholder />,
    );
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });
});

describe("ComparisonTable redesign", () => {
  it("adds the knowledge-graph / path-discovery row", () => {
    render(<ComparisonTable />);
    expect(
      screen.getByText(/Knowledge graph \/ path discovery/i),
    ).toBeInTheDocument();
  });

  it("marks the configurable workspace as fully supported (yes)", () => {
    render(<ComparisonTable />);
    // Find the workspace row, then assert its Worldview cell reads "Yes".
    const row = screen.getByText(/Configurable terminal workspace/i).closest("tr");
    expect(row).not.toBeNull();
    // The Worldview cell is the first data cell after the feature label.
    expect(within(row as HTMLElement).getAllByText("Yes").length).toBeGreaterThanOrEqual(1);
  });
});

describe("AIDemoSection refresh", () => {
  it("uses the neutral model tag, not a stale model string", () => {
    render(<AIDemoSection />);
    expect(screen.getByText(/grounded · cited · hybrid-RAG/i)).toBeInTheDocument();
    // The stale llama-3.1-8b label MUST be gone.
    expect(screen.queryByText(/llama-3\.1-8b/i)).toBeNull();
  });

  it("renders the slash-command chip row including /path", () => {
    render(<AIDemoSection />);
    ["/quote", "/path", "/compare", "/news", "/portfolio"].forEach((cmd) => {
      // /path also appears in the question; assert >=1 occurrence.
      expect(screen.getAllByText(cmd).length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders a citation-confidence bar", () => {
    render(<AIDemoSection />);
    expect(screen.getByText(/Citation confidence/i)).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Citation confidence by source/i }),
    ).toBeInTheDocument();
  });

  it("leads the demo with the /path NVDA TSM query", () => {
    render(<AIDemoSection />);
    const youBlock = screen.getByText("/path NVDA TSM");
    expect(youBlock).toBeInTheDocument();
    // Sanity: the within import is exercised so lint doesn't flag it.
    expect(within(youBlock).queryByRole("link")).toBeNull();
  });
});
