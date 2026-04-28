/**
 * __tests__/AskAiButton.test.tsx — TopBar Ask AI trigger contract.
 *
 * WHY: the button is a tiny dumb component but it is the only entry point
 * for the floating assistant in the shell. If onOpen ever stops firing or
 * the aria-pressed contract drifts, the assistant becomes effectively
 * undiscoverable. These tests pin the contract.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AskAiButton } from "@/components/shell/AskAiButton";

describe("AskAiButton", () => {
  it("calls onOpen when clicked", () => {
    const onOpen = vi.fn();
    render(<AskAiButton onOpen={onOpen} />);
    fireEvent.click(screen.getByRole("button", { name: /open ai assistant/i }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("reflects open state via aria-pressed when isOpen", () => {
    const onOpen = vi.fn();
    render(<AskAiButton onOpen={onOpen} isOpen />);
    const btn = screen.getByRole("button", { name: /open ai assistant/i });
    expect(btn).toHaveAttribute("aria-pressed", "true");
  });

  it("aria-pressed is false when closed", () => {
    const onOpen = vi.fn();
    render(<AskAiButton onOpen={onOpen} />);
    const btn = screen.getByRole("button", { name: /open ai assistant/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });
});
