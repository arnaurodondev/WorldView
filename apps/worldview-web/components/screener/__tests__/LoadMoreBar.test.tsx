/**
 * components/screener/__tests__/LoadMoreBar.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: LoadMoreBar handles the paginator chrome below the AG-Grid table.
 * The disabled-when-fetching contract is the single behaviour that
 * prevents double-firing the load-more click, and the count formatting
 * is the user-visible "X of Y loaded" readout. Both are pinned here.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoadMoreBar } from "@/components/screener/LoadMoreBar";

describe("LoadMoreBar", () => {
  it("renders the Load N more button with the next batch size", () => {
    render(
      <LoadMoreBar
        canLoadMore
        isFetching={false}
        accumulatorCount={50}
        total={1024}
        nextBatchSize={50}
        onLoadMore={() => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Load 50 more results/ }),
    ).toBeInTheDocument();
  });

  it("formats the count readout with locale grouping", () => {
    // WHY: the bar uses toLocaleString — large numbers must show grouping
    // separators so "1,024" doesn't render as "1024". This is the only
    // user-visible number formatting in the screener footer chrome.
    render(
      <LoadMoreBar
        canLoadMore
        isFetching={false}
        accumulatorCount={1234}
        total={56789}
        nextBatchSize={50}
        onLoadMore={() => {}}
      />,
    );
    // Match the canonical en-US grouping; jsdom uses Node's ICU which
    // honours the default locale (en-US in our test env).
    expect(screen.getByText(/1,234 of 56,789 loaded/)).toBeInTheDocument();
  });

  it("disables the button when isFetching is true and shows the busy copy", async () => {
    const onLoadMore = vi.fn();
    render(
      <LoadMoreBar
        canLoadMore
        isFetching
        accumulatorCount={50}
        total={100}
        nextBatchSize={50}
        onLoadMore={onLoadMore}
      />,
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Loading…");
    // Clicking a disabled button must not fire onLoadMore — prevents
    // double-fetch when the user mashes the button during the previous
    // request's in-flight period.
    await userEvent.click(btn).catch(() => {});
    expect(onLoadMore).not.toHaveBeenCalled();
  });

  it("disables the button when canLoadMore is false", () => {
    render(
      <LoadMoreBar
        canLoadMore={false}
        isFetching={false}
        accumulatorCount={100}
        total={100}
        nextBatchSize={0}
        onLoadMore={() => {}}
      />,
    );
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("calls onLoadMore when clicked in the enabled state", async () => {
    const onLoadMore = vi.fn();
    render(
      <LoadMoreBar
        canLoadMore
        isFetching={false}
        accumulatorCount={50}
        total={100}
        nextBatchSize={50}
        onLoadMore={onLoadMore}
      />,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });
});
