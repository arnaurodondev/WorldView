/**
 * components/primitives/__tests__/EmptyState.test.tsx
 *
 * WHY THIS EXISTS (Round-2 cross-surface request, item 4): the EmptyState
 * primitive grew two optional props — `icon` (lucide component, rendered
 * muted above the title) and `action` (ReactNode CTA slot, preferred over
 * legacy `cta`). These tests pin:
 *
 *   1. BACK-COMPAT: the original condition+copyKey+cta contract renders
 *      byte-identically when the new props are omitted — every existing
 *      call site (dashboard widgets, portfolio, screener…) is untouched.
 *   2. ICON: passing a lucide COMPONENT renders one decorative (aria-hidden)
 *      svg with the standard muted treatment; omitting it renders no svg.
 *   3. ACTION: the slot renders real interactive elements (onClick buttons,
 *      not just href Links) and wins over `cta` when both are passed —
 *      guaranteeing the single-slot invariant (no double CTA).
 *   4. COPY REGISTRY: the Round-2 instrument key reservations resolve, so the
 *      Round-3 migration of components/instrument/shared/EmptyState.tsx call
 *      sites cannot land before its copy exists.
 *
 * MOCK STRATEGY: none — pure presentational component; lucide icons render
 * plain <svg> under jsdom.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Newspaper } from "lucide-react";

import { EmptyState } from "@/components/primitives/EmptyState";
import { EMPTY_COPY } from "@/lib/copy/empty-states";

describe("EmptyState (primitives)", () => {
  // ── 1. Backward compatibility ──────────────────────────────────────────
  it("renders title + body from the copy registry with no new props (legacy contract)", () => {
    render(<EmptyState condition="empty-no-data" copyKey="screener.no-matches" />);

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(
      screen.getByText("Try widening the criteria or removing a filter."),
    ).toBeInTheDocument();
    // WHY: no icon prop → no svg. A regression that renders a default icon
    // would visually change ~30 existing call sites overnight.
    expect(document.querySelector("svg")).not.toBeInTheDocument();
  });

  it("still renders the legacy `cta` slot when `action` is absent", () => {
    render(
      <EmptyState
        condition="error"
        copyKey="generic.error"
        cta={<a href="/status">Status page</a>}
      />,
    );
    expect(screen.getByRole("link", { name: "Status page" })).toBeInTheDocument();
  });

  it("falls back to generic.<condition> copy for unknown keys", () => {
    // WHY: the per-condition fallback is what keeps a typo'd copyKey from
    // rendering a blank panel in production before the arch test catches it.
    // WHY a variable (not a literal prop): the empty-copy-dictionary arch
    // test scans every .tsx file (comments included) for string-literal
    // copyKey props — a literal here would be flagged as an unresolved key.
    // Dynamic expressions are exempt by design, which is exactly the escape
    // hatch this negative test needs.
    const deliberatelyMissingKey = "nonexistent.key";
    render(<EmptyState condition="loading" copyKey={deliberatelyMissingKey} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  // ── 2. icon prop ───────────────────────────────────────────────────────
  it("renders the lucide icon as a decorative (aria-hidden) muted svg", () => {
    const { container } = render(
      <EmptyState condition="empty-no-data" copyKey="instrument.no-articles" icon={Newspaper} />,
    );

    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    // WHY aria-hidden: the icon is a visual category cue only — the title is
    // the accessible information. Screen readers must not announce "image".
    expect(svg).toHaveAttribute("aria-hidden", "true");
    // WHY class assertions: pins the standard treatment (16px, muted 60%)
    // so the Round-3 consolidation from instrument/shared/EmptyState.tsx is
    // pixel-identical with that component's existing rendering.
    expect(svg).toHaveClass("size-4");
    expect(svg).toHaveClass("text-muted-foreground/60");
  });

  // ── 3. action prop ─────────────────────────────────────────────────────
  it("renders an interactive `action` button and fires its onClick", async () => {
    const onRetry = vi.fn();
    render(
      <EmptyState
        condition="error"
        copyKey="generic.error"
        action={
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        }
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    // WHY: the whole point of `action` over href-only `cta` — real onClick
    // handlers (retry/regenerate) must work, not just navigation.
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("prefers `action` over legacy `cta` when both are passed (single-slot invariant)", () => {
    render(
      <EmptyState
        condition="error"
        copyKey="generic.error"
        cta={<button type="button">Legacy CTA</button>}
        action={<button type="button">New action</button>}
      />,
    );

    expect(screen.getByRole("button", { name: "New action" })).toBeInTheDocument();
    // WHY queryBy (absence): both rendering would show two stacked buttons —
    // the exact double-CTA glitch the single-slot rule prevents.
    expect(screen.queryByRole("button", { name: "Legacy CTA" })).not.toBeInTheDocument();
  });

  // ── 4. Round-2 instrument copy-key reservations ────────────────────────
  it("resolves every Round-2 instrument copy key in the registry", () => {
    // WHY enumerate explicitly (not Object.keys filter): the Round-3
    // migration plan references these exact keys; a rename in the registry
    // must fail HERE, not at migration time.
    const reserved = [
      "instrument.no-articles",
      "instrument.no-contradictions",
      "instrument.graph-timeout",
      "instrument.graph-no-filter-matches",
      "instrument.no-connections",
      "instrument.no-entity-context",
    ];
    for (const key of reserved) {
      expect(EMPTY_COPY[key], `missing copy for ${key}`).toBeDefined();
      expect(EMPTY_COPY[key]?.title.length).toBeGreaterThan(0);
      expect(EMPTY_COPY[key]?.body.length).toBeGreaterThan(0);
    }
  });
});
