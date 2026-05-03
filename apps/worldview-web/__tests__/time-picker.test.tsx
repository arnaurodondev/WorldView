/**
 * __tests__/time-picker.test.tsx — Unit tests for TimePicker
 *
 * WHY THIS EXISTS: The clamping behaviour (HH > 23 → 23, MM > 59 → 59) must
 * be verified because institutional users type fast and expect auto-correction
 * rather than cryptic validation errors. These tests ensure the clamp is
 * applied correctly on blur.
 *
 * DATA SOURCE: No S9 calls — pure UI.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TimePicker } from "@/components/ui/time-picker";

// ── Render helpers ────────────────────────────────────────────────────────

function hhInput() {
  return screen.getByRole("textbox", { name: "Hours" });
}
function mmInput() {
  return screen.getByRole("textbox", { name: "Minutes" });
}

// ── Initial value parsing ─────────────────────────────────────────────────

describe("TimePicker — initial value", () => {
  it("parses '14:30' and populates HH=14, MM=30", () => {
    render(<TimePicker value="14:30" onChange={vi.fn()} />);
    expect(hhInput()).toHaveValue("14");
    expect(mmInput()).toHaveValue("30");
  });

  it("shows '00' and '00' when value is undefined", () => {
    render(<TimePicker value={undefined} onChange={vi.fn()} />);
    expect(hhInput()).toHaveValue("00");
    expect(mmInput()).toHaveValue("00");
  });
});

// ── HH clamping ──────────────────────────────────────────────────────────

describe("TimePicker — HH clamping on blur", () => {
  it("clamps HH=25 → 23 on blur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TimePicker value="10:00" onChange={onChange} />);
    const hh = hhInput();
    await user.clear(hh);
    await user.type(hh, "25");
    await user.tab(); // blur the HH input
    // onChange must be called with "23:00"
    expect(onChange).toHaveBeenCalledWith(
      expect.stringMatching(/^23:/),
    );
  });

  it("clamps HH=99 → 23 on blur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TimePicker value="00:00" onChange={onChange} />);
    const hh = hhInput();
    await user.clear(hh);
    await user.type(hh, "99");
    await user.tab();
    expect(onChange).toHaveBeenCalledWith(
      expect.stringMatching(/^23:/),
    );
  });
});

// ── MM clamping ──────────────────────────────────────────────────────────

describe("TimePicker — MM clamping on blur", () => {
  it("clamps MM=60 → 59 on blur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TimePicker value="10:00" onChange={onChange} />);
    const mm = mmInput();
    await user.clear(mm);
    await user.type(mm, "60");
    await user.tab();
    expect(onChange).toHaveBeenCalledWith(
      expect.stringMatching(/:59$/),
    );
  });

  it("clamps MM=99 → 59 on blur", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TimePicker value="10:00" onChange={onChange} />);
    const mm = mmInput();
    await user.clear(mm);
    await user.type(mm, "99");
    await user.tab();
    expect(onChange).toHaveBeenCalledWith(
      expect.stringMatching(/:59$/),
    );
  });
});

// ── onChange format ───────────────────────────────────────────────────────

describe("TimePicker — onChange output format", () => {
  it("emits 'HH:MM' with zero-padded values", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TimePicker value="00:00" onChange={onChange} />);
    const hh = hhInput();
    await user.clear(hh);
    await user.type(hh, "9");
    await user.tab();
    // Single digit 9 should be zero-padded to "09"
    const lastCall = onChange.mock.calls.at(-1)?.[0] as string;
    expect(lastCall).toMatch(/^\d{2}:\d{2}$/);
    expect(lastCall.startsWith("09")).toBe(true);
  });
});
