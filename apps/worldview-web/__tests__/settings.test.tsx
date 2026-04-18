/**
 * __tests__/settings.test.tsx — Unit tests for Settings, 404, and Error pages
 *
 * WHY THIS EXISTS: Wave F-13 introduces three new pages (Settings, not-found,
 * error) that must render correctly in isolation. These tests verify:
 *   1. Settings page renders all three tab buttons (Profile/Notifications/Appearance)
 *   2. 404 not-found page renders the "not found" text and a back link
 *   3. Error boundary page renders the error message and the reset (retry) button
 *
 * WHY MOCK NEXT/NAVIGATION: Settings page uses no navigation hooks directly,
 * but shadcn Tabs renders with Radix primitives that may reference navigation
 * context. Mocking it preventively avoids "invariant" errors in test environments.
 *
 * WHY MOCK USEAUTH: Settings page's ProfileTab reads user data from useAuth.
 * Without a mock, the test would need the full AuthContext provider tree
 * (including gateway, token refresh timers, etc.). Mocking gives us a clean,
 * predictable user object without side effects.
 *
 * DATA SOURCE: Mocked (no real S9 calls)
 * DESIGN REFERENCE: PRD-0028 §6.5 Settings, 404, Error pages
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Next.js router mock ───────────────────────────────────────────────────────
// WHY: shadcn Tabs and link components may internally reference the Next.js
// App Router context. In vitest/jsdom the App Router isn't mounted, so we mock
// it to prevent "useRouter must be used inside a router" invariant errors.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/settings"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY: Settings page reads user.name, user.email, user.avatar_url via useAuth.
// We inject a fixed user object so tests don't depend on a real auth context.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "test@example.com",
      name: "Test User",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Imports (after mocks) ─────────────────────────────────────────────────────
// WHY imports after vi.mock(): vitest hoists vi.mock() calls to the top of the
// file regardless of order, but placing imports after the mock blocks is the
// conventional pattern that makes the dependency on the mock explicit.
import SettingsPage from "@/app/(app)/settings/page";
import NotFoundPage from "@/app/not-found";
import ErrorPage from "@/app/error";

// ── Settings page tests ───────────────────────────────────────────────────────

describe("SettingsPage", () => {
  beforeEach(() => {
    // WHY beforeEach re-render: Each test should start with a clean render.
    // Tests within the describe block may mutate shared DOM state (e.g., tab
    // activation) so starting fresh prevents cross-test contamination.
  });

  it("renders the Settings page heading", () => {
    render(<SettingsPage />);
    // WHY getByRole h1: the page heading is the primary landmark for screen readers.
    // Testing by role+name is more robust than testing by text content alone.
    expect(screen.getByRole("heading", { name: /settings/i })).toBeInTheDocument();
  });

  it("renders the Profile tab button", () => {
    render(<SettingsPage />);
    // WHY check for tab buttons: The three tabs are the primary navigation
    // within this page. If they don't render, the entire settings UI is broken.
    expect(screen.getByRole("tab", { name: /profile/i })).toBeInTheDocument();
  });

  it("renders the Notifications tab button", () => {
    render(<SettingsPage />);
    expect(screen.getByRole("tab", { name: /notifications/i })).toBeInTheDocument();
  });

  it("renders the Appearance tab button", () => {
    render(<SettingsPage />);
    expect(screen.getByRole("tab", { name: /appearance/i })).toBeInTheDocument();
  });

  it("shows Profile tab content by default (user email visible)", () => {
    render(<SettingsPage />);
    // WHY test the default tab content: Profile is defaultValue="profile".
    // The user email is a key piece of data displayed in the profile tab.
    // If useAuth mock is working AND the tab is active, the email shows up.
    // WHY getAllByText: email appears twice in the profile tab — once in the
    // avatar row (compact display) and once in the <dl> field row. Both are
    // correct; we confirm at least one is present rather than expecting exactly one.
    expect(screen.getAllByText("test@example.com").length).toBeGreaterThan(0);
  });

  it("shows Profile tab content with the mocked user name", () => {
    render(<SettingsPage />);
    // WHY check name: confirms user data flows from the mock into ProfileTab.
    // Multiple instances may appear (in the top avatar row and the dl row).
    expect(screen.getAllByText("Test User").length).toBeGreaterThan(0);
  });

  it("shows Notifications tab content when clicked", async () => {
    render(<SettingsPage />);
    const user = userEvent.setup();

    // WHY click the tab: verifies tab navigation works and the Notifications
    // panel content becomes visible. Tests tab switching behaviour.
    const notifTab = screen.getByRole("tab", { name: /notifications/i });
    await user.click(notifTab);

    // WHY "High-severity alerts": this is the first notification type label
    // in NOTIFICATION_TYPES — a stable anchor for the tab content test.
    expect(screen.getByText(/high-severity alerts/i)).toBeInTheDocument();
  });

  it("shows Appearance tab content when clicked", async () => {
    render(<SettingsPage />);
    const user = userEvent.setup();

    const appearanceTab = screen.getByRole("tab", { name: /appearance/i });
    await user.click(appearanceTab);

    // WHY "permanently enabled": the appearance tab explains dark mode with
    // "Dark mode" as a label and "Permanently enabled" in the description.
    expect(screen.getByText(/permanently enabled/i)).toBeInTheDocument();
  });

  it("renders notification type switch toggles on Notifications tab", async () => {
    render(<SettingsPage />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("tab", { name: /notifications/i }));

    // WHY check for switches: the notification tab's primary UI is toggle switches.
    // If they don't render, the tab is effectively empty.
    const switches = screen.getAllByRole("switch");
    expect(switches.length).toBeGreaterThan(0);
  });
});

// ── 404 not-found page tests ──────────────────────────────────────────────────

describe("NotFoundPage", () => {
  it("renders the 404 not found heading", () => {
    render(<NotFoundPage />);
    // WHY getByRole heading: the h1 is the primary signal that the 404 page
    // rendered correctly. Tests by role is more resilient than matching text.
    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
  });

  it("renders the Error 404 label", () => {
    render(<NotFoundPage />);
    // WHY check the "Error 404" label: it confirms the error code is visible
    // for users who want to communicate the issue to support.
    expect(screen.getByText(/error 404/i)).toBeInTheDocument();
  });

  it("renders a link back to the dashboard", () => {
    render(<NotFoundPage />);
    // WHY check for dashboard link: the primary recovery action from a 404
    // is navigating back to a known-good page. If this link is missing, users
    // are stranded on the error page with no exit.
    const dashboardLink = screen.getByRole("link", { name: /back to dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");
  });

  it("renders a link to the home page", () => {
    render(<NotFoundPage />);
    // WHY check home link: secondary escape path for unauthenticated users
    // who don't have a dashboard to return to.
    const homeLink = screen.getByRole("link", { name: /go to home/i });
    expect(homeLink).toBeInTheDocument();
    expect(homeLink).toHaveAttribute("href", "/");
  });
});

// ── Error boundary page tests ─────────────────────────────────────────────────

describe("ErrorPage", () => {
  // WHY mock error object: ErrorPage receives an Error instance from Next.js.
  // We create a minimal Error to satisfy the component's prop type.
  const mockError = new Error("Test error") as Error & { digest?: string };
  const mockReset = vi.fn();

  beforeEach(() => {
    mockReset.mockClear();
  });

  it("renders the error heading", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    // WHY check heading: the h1 is the first thing a user reads on an error page.
    // Testing it confirms the component mounted without throwing during render.
    expect(
      screen.getByRole("heading", { name: /unexpected error/i }),
    ).toBeInTheDocument();
  });

  it("renders the error message description", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    // WHY check error message text: confirms the user-facing explanation renders.
    // We test for a substring of the message so the test isn't brittle to
    // minor wording changes.
    expect(screen.getByText(/unexpected error occurred/i)).toBeInTheDocument();
  });

  it("renders the Try again button", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    // WHY check retry button: this is the primary recovery action on the error page.
    // The button calls reset() which re-renders the failed component tree.
    const retryButton = screen.getByRole("button", { name: /try again/i });
    expect(retryButton).toBeInTheDocument();
  });

  it("calls reset() when Try again is clicked", async () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    const user = userEvent.setup();

    // WHY test that reset() is called: the reset prop is the core functionality
    // of the error boundary page. If the button doesn't call reset(), the
    // "Try again" button does nothing — a silent failure for users.
    const retryButton = screen.getByRole("button", { name: /try again/i });
    await user.click(retryButton);

    expect(mockReset).toHaveBeenCalledOnce();
  });

  it("renders a link back to the dashboard", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    // WHY check dashboard link: secondary escape path if reset() fails to fix
    // the issue. Users need a way out of the error page.
    const dashboardLink = screen.getByRole("link", { name: /back to dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");
  });
});
