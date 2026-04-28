/**
 * __tests__/InstrumentAskAiButton.test.tsx — page-context Ask AI floater.
 *
 * Pins the contract that:
 *   - the floating trigger is visible while closed
 *   - clicking it mounts the AskAiPanel
 *   - the contextHint forwarded to the panel actually surfaces in DOM
 *
 * AskAiPanel is mocked so we can assert on the props it receives without
 * pulling in the full SSE-streaming machinery (covered by AskAiPanel.test).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock the panel before importing the button so the import boundary picks up the stub.
vi.mock("@/components/shell/AskAiPanel", () => ({
  AskAiPanel: ({ contextHint, onClose }: { contextHint?: string; onClose: () => void }) => (
    <div data-testid="mock-ask-ai-panel">
      <span data-testid="ctx">{contextHint}</span>
      <button onClick={onClose}>close</button>
    </div>
  ),
}));

import { InstrumentAskAiButton } from "@/components/instrument/InstrumentAskAiButton";

describe("InstrumentAskAiButton", () => {
  it("renders the floating trigger labelled with the ticker", () => {
    render(<InstrumentAskAiButton ticker="AAPL" />);
    const btn = screen.getByRole("button", { name: /ask ai about aapl/i });
    expect(btn).toBeInTheDocument();
  });

  it("opens the AskAiPanel and forwards a context hint with price + recent move", () => {
    render(
      <InstrumentAskAiButton
        ticker="AAPL"
        currentPrice={193.5}
        recentBars={[
          { timestamp: "2026-04-01T00:00:00Z", open: 180, high: 181, low: 179, close: 180, volume: 1 },
          { timestamp: "2026-04-29T00:00:00Z", open: 195, high: 196, low: 192, close: 193.5, volume: 1 },
        ]}
        fundamentals={{ pe_ratio: 28.6, market_cap: 3_000_000_000 } as never}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /ask ai about aapl/i }));

    const panel = screen.getByTestId("mock-ask-ai-panel");
    const ctx = screen.getByTestId("ctx").textContent ?? "";
    expect(panel).toBeInTheDocument();
    expect(ctx).toMatch(/Ticker: AAPL/);
    expect(ctx).toMatch(/price \$193\.50/);
    // 30d-move pct ((193.5 − 180) / 180) ≈ +7.50%
    expect(ctx).toMatch(/2d move \+7\.50%/);
    expect(ctx).toMatch(/P\/E 28\.6/);
    expect(ctx).toMatch(/mcap \$3\.0B/);
  });

  it("hides the trigger while the panel is open and shows it again on close", () => {
    render(<InstrumentAskAiButton ticker="MSFT" />);
    const btn = screen.getByRole("button", { name: /ask ai about msft/i });
    fireEvent.click(btn);
    // Trigger gone, panel mounted
    expect(screen.queryByRole("button", { name: /ask ai about msft/i })).toBeNull();
    // Close via the mock panel's button
    fireEvent.click(screen.getByText("close"));
    expect(screen.getByRole("button", { name: /ask ai about msft/i })).toBeInTheDocument();
  });
});
