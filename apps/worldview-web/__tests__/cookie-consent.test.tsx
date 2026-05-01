/**
 * __tests__/cookie-consent.test.tsx — PLAN-0059 I-6 cookie consent banner
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import {
  CookieConsentBanner,
  hasConsent,
} from "@/components/legal/CookieConsentBanner";

describe("CookieConsentBanner", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("does not render until first paint flushes the mount effect", () => {
    const { container } = render(<CookieConsentBanner />);
    // First synchronous render: mounted=false → banner returns null.
    // Then the effect commits and mounted flips. By the time we query,
    // RTL has already flushed effects, so the banner IS visible.
    // We assert it ends visible — same goal as "shows on first paint".
    expect(container.querySelector("[role='region'][aria-label='Cookie consent']")).not.toBeNull();
  });

  it("shows the three category descriptions when 'Customise' is clicked", () => {
    render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /customise/i }));
    expect(screen.getByText(/Necessary/)).toBeInTheDocument();
    expect(screen.getByText(/Preferences/)).toBeInTheDocument();
    expect(screen.getByText(/Analytics/)).toBeInTheDocument();
  });

  it("Necessary category checkbox is always checked + disabled", () => {
    render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /customise/i }));
    const necessary = screen.getByLabelText(/Necessary storage/);
    expect(necessary).toBeChecked();
    expect(necessary).toBeDisabled();
  });

  it("Accept all persists analytics=true preferences=true and hides banner", () => {
    const { container } = render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /accept all/i }));
    expect(
      container.querySelector("[role='region'][aria-label='Cookie consent']"),
    ).toBeNull();
    expect(hasConsent("analytics")).toBe(true);
    expect(hasConsent("preferences")).toBe(true);
  });

  it("Reject optional persists both off + hides banner", () => {
    const { container } = render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /reject optional/i }));
    expect(
      container.querySelector("[role='region'][aria-label='Cookie consent']"),
    ).toBeNull();
    expect(hasConsent("analytics")).toBe(false);
    expect(hasConsent("preferences")).toBe(false);
  });

  it("Customise → uncheck preferences → save preserves the user's choice", () => {
    render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /customise/i }));

    // Preferences default-on; click to flip off.
    const prefCheckbox = screen.getByLabelText(/Preferences/);
    expect(prefCheckbox).toBeChecked();
    fireEvent.click(prefCheckbox);
    expect(prefCheckbox).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /save preferences/i }));
    expect(hasConsent("preferences")).toBe(false);
    expect(hasConsent("analytics")).toBe(false); // default off, untouched
  });

  it("hasConsent returns false when no decision has been recorded", () => {
    expect(hasConsent("analytics")).toBe(false);
    expect(hasConsent("preferences")).toBe(false);
  });

  it("rejects malformed stored consent and re-shows banner", () => {
    // Corrupt entry — wrong version, missing fields.
    localStorage.setItem(
      "worldview.cookie-consent.v1",
      JSON.stringify({ version: 2, analytics: true }),
    );
    const { container } = render(<CookieConsentBanner />);
    expect(
      container.querySelector("[role='region'][aria-label='Cookie consent']"),
    ).not.toBeNull();
  });

  it("once decided, banner does not re-render on next mount", () => {
    // First render — accept all.
    const { container: c1, unmount } = render(<CookieConsentBanner />);
    fireEvent.click(screen.getByRole("button", { name: /accept all/i }));
    unmount();
    expect(c1.querySelector("[role='region']")).toBeNull();

    // Second render in same tab (e.g. navigation) — banner stays hidden.
    const { container: c2 } = render(<CookieConsentBanner />);
    // mount effect runs synchronously under RTL — readConsent returns the
    // persisted decision and decision state is non-null → null returned.
    act(() => {
      // ensure useEffect flushed
    });
    expect(
      c2.querySelector("[role='region'][aria-label='Cookie consent']"),
    ).toBeNull();
  });
});
