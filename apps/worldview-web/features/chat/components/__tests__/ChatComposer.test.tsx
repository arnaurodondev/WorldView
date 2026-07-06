/**
 * ChatComposer.test.tsx — persistent platform disclaimer guard.
 *
 * WHAT THIS GUARDS:
 *   The composer must ALWAYS render the "not financial advice" disclaimer.
 *   Because the composer is the one region mounted on every chat view, this
 *   line is our liability-coverage anchor for the whole chat surface — if it
 *   silently disappears (e.g. someone refactors the footer), the platform
 *   loses that coverage. This test fails loudly if the copy is removed or
 *   materially reworded.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ChatComposer } from "../ChatComposer";

describe("ChatComposer disclaimer", () => {
  // Minimal required props — the disclaimer is unconditional chrome, so a bare
  // controlled composer (empty value, not streaming) is enough to assert it.
  const baseProps = {
    value: "",
    onChange: vi.fn(),
    onSend: vi.fn(),
    isStreaming: false,
  } as const;

  it("renders the 'not financial advice' platform disclaimer", () => {
    render(<ChatComposer {...baseProps} />);

    // Match on the load-bearing phrase (case-insensitive) rather than the full
    // sentence so trivial punctuation tweaks don't break the test, while the
    // legally-required substance ("not financial advice") is still enforced.
    expect(
      screen.getByText(/not financial advice or a recommendation/i),
    ).toBeInTheDocument();
  });

  it("exposes the disclaimer via a stable data-cell hook", () => {
    const { container } = render(<ChatComposer {...baseProps} />);
    const note = container.querySelector('[data-cell="composer-disclaimer"]');
    expect(note).not.toBeNull();
    expect(note?.textContent).toMatch(/informational purposes only/i);
  });
});
