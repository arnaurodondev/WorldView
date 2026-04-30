/**
 * __tests__/notification-prefs.test.tsx — PLAN-0051 T-D-4-07 prefs lib + dialog.
 *
 * WHY THIS FILE: covers the notification-prefs storage layer + the dialog
 * that edits it. The lib is pure logic (no React) so we test it directly;
 * the dialog is tested through render/user-event.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  loadNotificationPrefs,
  saveNotificationPrefs,
  isValidTimeString,
  isInQuietHours,
  DEFAULT_PREFS,
} from "@/lib/notification-prefs";
import { NotificationPreferencesDialog } from "@/components/alerts/NotificationPreferencesDialog";

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe("lib/notification-prefs", () => {
  it("returns DEFAULT_PREFS when localStorage is empty", () => {
    const prefs = loadNotificationPrefs();
    expect(prefs).toEqual(DEFAULT_PREFS);
  });

  it("round-trips a saved preferences blob", () => {
    saveNotificationPrefs({
      inAppEnabled: false,
      emailDigestOptIn: true,
      browserPushEnabled: false,
      quietHoursStart: "22:00",
      quietHoursEnd: "06:00",
      severityFloor: "HIGH",
    });
    const loaded = loadNotificationPrefs();
    expect(loaded.inAppEnabled).toBe(false);
    expect(loaded.emailDigestOptIn).toBe(true);
    expect(loaded.severityFloor).toBe("HIGH");
    expect(loaded.quietHoursStart).toBe("22:00");
    expect(loaded.quietHoursEnd).toBe("06:00");
  });

  it("rejects malformed quiet-hours values on load", () => {
    // Hand-edited blob with a garbage time string.
    localStorage.setItem(
      "worldview:notificationPrefs:v1",
      JSON.stringify({ ...DEFAULT_PREFS, quietHoursStart: "not-a-time" }),
    );
    const loaded = loadNotificationPrefs();
    expect(loaded.quietHoursStart).toBeUndefined();
  });

  it("isValidTimeString accepts HH:mm and rejects garbage", () => {
    expect(isValidTimeString("00:00")).toBe(true);
    expect(isValidTimeString("23:59")).toBe(true);
    expect(isValidTimeString("9:30")).toBe(false); // missing leading zero
    expect(isValidTimeString("24:00")).toBe(false);
    expect(isValidTimeString("foo")).toBe(false);
    expect(isValidTimeString(null)).toBe(false);
  });

  it("isInQuietHours handles wrap-around windows", () => {
    const wrap = { ...DEFAULT_PREFS, quietHoursStart: "22:00", quietHoursEnd: "06:00" };
    // 23:30 → inside the wrap window
    const lateNight = new Date();
    lateNight.setHours(23, 30, 0, 0);
    expect(isInQuietHours(wrap, lateNight)).toBe(true);
    // 12:00 → outside
    const noon = new Date();
    noon.setHours(12, 0, 0, 0);
    expect(isInQuietHours(wrap, noon)).toBe(false);
  });

  it("isInQuietHours returns false when no window is configured", () => {
    expect(isInQuietHours(DEFAULT_PREFS)).toBe(false);
  });
});

describe("NotificationPreferencesDialog", () => {
  it("opens and renders all preference controls", async () => {
    const user = userEvent.setup();
    render(<NotificationPreferencesDialog />);
    await user.click(screen.getByRole("button", { name: /Notification preferences/i }));

    // Toggles
    expect(await screen.findByText(/In-app notifications/i)).toBeInTheDocument();
    expect(screen.getByText(/Daily email digest/i)).toBeInTheDocument();
    expect(screen.getByText(/Browser notifications/i)).toBeInTheDocument();
    // Severity select
    expect(screen.getByLabelText(/Minimum alert severity/i)).toBeInTheDocument();
    // Quiet-hours inputs
    expect(screen.getByLabelText(/Quiet hours start/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Quiet hours end/i)).toBeInTheDocument();
  });

  it("Save persists the chosen severity floor to localStorage", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<NotificationPreferencesDialog onSaved={onSaved} />);
    await user.click(screen.getByRole("button", { name: /Notification preferences/i }));

    const select = await screen.findByLabelText(/Minimum alert severity/i);
    await user.selectOptions(select, "HIGH");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const persisted = loadNotificationPrefs();
    expect(persisted.severityFloor).toBe("HIGH");
  });
});
