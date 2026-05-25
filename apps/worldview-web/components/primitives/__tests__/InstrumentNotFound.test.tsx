/**
 * components/primitives/__tests__/InstrumentNotFound.test.tsx
 *
 * WHY THIS EXISTS (PRD-0089 F2 step 10): the InstrumentNotFound primitive
 * is the canonical "unknown ticker" surface for the instrument page 404
 * branch. These tests pin three behavioural contracts the consumer site
 * (InstrumentPageClient) relies on:
 *
 *   1. The attempted ticker renders in uppercase mono — finance UX
 *      convention; a lowercase render would suggest the request was
 *      *not* normalised through the slug middleware.
 *   2. The "Did you mean" list renders only when `suggestedTickers`
 *      has at least one entry, with each ticker linking to
 *      `/instruments/{TICKER}`. Future S9 fuzzy-match wiring just needs
 *      to feed values into the prop — no primitive change.
 *   3. The "Browse all instruments" escape link is always present and
 *      points to `/screener`.
 *
 * Plus one architectural guard:
 *   4. No light-mode tokens leak in (terminal-dark only, F1 §1).
 *
 * MOCK STRATEGY: this is a pure server-renderable primitive (Link is
 * RSC-compatible). next/link works directly under React Testing Library
 * with no mocking required — it renders a plain `<a>` in test env.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InstrumentNotFound } from "@/components/primitives/InstrumentNotFound";

describe("InstrumentNotFound", () => {
  it("renders the attempted ticker uppercase + mono", () => {
    // WHY pass lowercase: tests the defensive .toUpperCase() in the
    // primitive — the middleware normally uppercases, but a future
    // bypass (test harness, alt route) must not leak lowercase.
    render(<InstrumentNotFound attemptedTicker="aapl" />);

    const tickerNode = screen.getByText("AAPL");
    expect(tickerNode).toBeInTheDocument();
    // WHY assert font-mono: tickers MUST always render in IBM Plex Mono
    // (PRD-0088 §6.11). A regression to a proportional font would jitter
    // any future list view rendering the same primitive.
    expect(tickerNode).toHaveClass("font-mono");
    expect(tickerNode).toHaveClass("tabular-nums");
  });

  it("renders the 'INSTRUMENT NOT FOUND' label with the negative palette token", () => {
    render(<InstrumentNotFound attemptedTicker="ZZZZ" />);

    const label = screen.getByText("INSTRUMENT NOT FOUND");
    expect(label).toBeInTheDocument();
    // WHY assert text-negative (not text-destructive / text-red-500):
    // DESIGN_SYSTEM.md maps error / loss to `--negative` (#EF5350).
    // text-destructive is reserved for delete actions; raw Tailwind red
    // shades are banned by the no-off-palette-colors arch test.
    expect(label).toHaveClass("text-negative");
  });

  it("renders the 'Did you mean' suggestions list when provided", () => {
    render(
      <InstrumentNotFound
        attemptedTicker="APPL"
        suggestedTickers={["AAPL", "AMZN"]}
      />,
    );

    // WHY assert presence of the header label: confirms the conditional
    // branch fired (vs. silently dropping a non-empty array).
    expect(screen.getByText("Did you mean:")).toBeInTheDocument();

    // WHY assert role="link" and href: future renames of the slug
    // route would break the link target. Asserting the actual href
    // catches that regression at test time.
    const aapl = screen.getByRole("link", { name: "AAPL" });
    expect(aapl).toHaveAttribute("href", "/instruments/AAPL");

    const amzn = screen.getByRole("link", { name: "AMZN" });
    expect(amzn).toHaveAttribute("href", "/instruments/AMZN");
  });

  it("hides the 'Did you mean' section when suggestions are empty", () => {
    render(<InstrumentNotFound attemptedTicker="ZZZZ" suggestedTickers={[]} />);

    // WHY queryByText (not getByText): expect *absence*. getByText
    // would throw, masking the intent.
    expect(screen.queryByText("Did you mean:")).not.toBeInTheDocument();
  });

  it("always renders the 'Browse all instruments' escape link", () => {
    render(<InstrumentNotFound attemptedTicker="ZZZZ" />);

    // WHY name regex: the arrow glyph "→" is part of the visible label,
    // but accessible-name normalisation may collapse it. A regex anchored
    // on "Browse all instruments" survives both renderings.
    const link = screen.getByRole("link", { name: /Browse all instruments/i });
    expect(link).toHaveAttribute("href", "/screener");
  });

  it("does not leak any light-mode classes", () => {
    // WHY this guard: the whole platform is dark-mode-only (F1 §1, RULES.md).
    // A regression that adds `dark:` variants (which implies a light branch
    // exists) or raw `bg-white` / `text-black` would betray the contract.
    const { container } = render(<InstrumentNotFound attemptedTicker="ZZZZ" />);
    const html = container.innerHTML;
    // The negation list — any of these strings appearing is a regression.
    expect(html).not.toMatch(/\bdark:/);
    expect(html).not.toMatch(/\bbg-white\b/);
    expect(html).not.toMatch(/\btext-black\b/);
    expect(html).not.toMatch(/\bbg-slate-\d+\b/);
  });

  it("truncates suggestions beyond 5 entries", () => {
    // WHY a defensive cap: future S9 contract caps suggestions at 5,
    // but a misbehaving backend or test harness might pass more.
    render(
      <InstrumentNotFound
        attemptedTicker="ZZZZ"
        suggestedTickers={["AA", "BB", "CC", "DD", "EE", "FF", "GG"]}
      />,
    );

    // First 5 must be present.
    for (const t of ["AA", "BB", "CC", "DD", "EE"]) {
      expect(screen.getByRole("link", { name: t })).toBeInTheDocument();
    }
    // 6th and 7th must NOT render.
    expect(screen.queryByRole("link", { name: "FF" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "GG" })).not.toBeInTheDocument();
  });
});
