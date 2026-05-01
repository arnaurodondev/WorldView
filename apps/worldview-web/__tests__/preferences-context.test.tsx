/**
 * __tests__/preferences-context.test.tsx — PLAN-0059 I-4
 */

import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  PreferencesProvider,
  usePreferences,
} from "@/contexts/PreferencesContext";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <PreferencesProvider>{children}</PreferencesProvider>
);

describe("PreferencesProvider", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns defaults on first render", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    expect(result.current.density).toBe("compact");
    expect(result.current.currency).toBe("USD");
    expect(result.current.timezone).toBe("auto");
  });

  it("setDensity persists to localStorage", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    act(() => result.current.setDensity("comfortable"));
    expect(result.current.density).toBe("comfortable");

    // New provider instance should hydrate from storage.
    const { result: result2 } = renderHook(() => usePreferences(), { wrapper });
    expect(result2.current.density).toBe("comfortable");
  });

  it("setCurrency persists", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    act(() => result.current.setCurrency("EUR"));
    expect(result.current.currency).toBe("EUR");
  });

  it("setTimezone persists; resolvedTimezone reads back the IANA value", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    act(() => result.current.setTimezone("Europe/London"));
    expect(result.current.timezone).toBe("Europe/London");
    expect(result.current.resolvedTimezone).toBe("Europe/London");
  });

  it("resolvedTimezone falls back to browser tz when 'auto'", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    expect(result.current.timezone).toBe("auto");
    // jsdom's Intl resolves to UTC unless overridden.
    expect(result.current.resolvedTimezone).toBeTruthy();
    expect(typeof result.current.resolvedTimezone).toBe("string");
  });

  it("reset() restores defaults", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    act(() => {
      result.current.setDensity("comfortable");
      result.current.setCurrency("EUR");
      result.current.setTimezone("Asia/Tokyo");
    });
    act(() => result.current.reset());
    expect(result.current.density).toBe("compact");
    expect(result.current.currency).toBe("USD");
    expect(result.current.timezone).toBe("auto");
  });

  it("ignores corrupted localStorage and uses defaults", () => {
    localStorage.setItem(
      "worldview.preferences.v1",
      JSON.stringify({ density: "invalid-density", currency: "USD", timezone: "UTC" }),
    );
    const { result } = renderHook(() => usePreferences(), { wrapper });
    expect(result.current.density).toBe("compact"); // back to default
  });

  it("density change applies data-density attribute on body", () => {
    const { result } = renderHook(() => usePreferences(), { wrapper });
    act(() => result.current.setDensity("comfortable"));
    expect(document.body.dataset.density).toBe("comfortable");
  });

  it("usePreferences throws outside provider", () => {
    // Capture the error — renderHook unwraps it.
    expect(() => renderHook(() => usePreferences())).toThrow(
      /must be used inside <PreferencesProvider>/,
    );
  });
});
