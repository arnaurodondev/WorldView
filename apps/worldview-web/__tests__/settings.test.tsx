/**
 * __tests__/settings.test.tsx — Settings nested-route tests + 404/Error
 *
 * PLAN-0059 I-3: settings was rewritten from a single tabbed page into a
 * nested-route tree (`/settings/profile`, `/settings/notifications`,
 * `/settings/appearance`, plus placeholder routes). The legacy "tabs role"
 * assertions are replaced with assertions against the new sidebar layout +
 * per-route page content. Same SR-visible behaviour, different DOM shape.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/settings/profile"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  redirect: vi.fn(),
  // WHY notFound: settings/security page calls notFound() when
  // NEXT_PUBLIC_ENABLE_SECURITY is not set — the mock must export it.
  notFound: vi.fn(() => { throw new Error("NEXT_NOT_FOUND"); }),
}));

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

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

// WHY gateway mock: SettingsNotificationsPage calls getNotificationPreferences.
// Without a mock, the query is in loading state during synchronous render
// and shows skeletons instead of switches. Returning null simulates "no prefs
// row yet" — the page falls back to DEFAULT_PREFS and renders all switches.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getNotificationPreferences: vi.fn().mockResolvedValue(null),
    updateNotificationPreferences: vi.fn().mockResolvedValue({}),
  })),
}));

import SettingsLayout from "@/app/(app)/settings/layout";
import SettingsProfilePage from "@/app/(app)/settings/profile/page";
import SettingsNotificationsPage from "@/app/(app)/settings/notifications/page";
import SettingsAppearancePage from "@/app/(app)/settings/appearance/page";
import SettingsSecurityPage from "@/app/(app)/settings/security/page";
import NotFoundPage from "@/app/not-found";
import ErrorPage from "@/app/error";

// ── Settings layout (sidebar nav) tests ────────────────────────────────────

describe("SettingsLayout", () => {
  it("renders the Settings page heading", () => {
    render(
      <SettingsLayout>
        <div />
      </SettingsLayout>,
    );
    expect(screen.getByRole("heading", { name: /settings/i })).toBeInTheDocument();
  });

  it("renders sidebar nav items for each section", () => {
    render(
      <SettingsLayout>
        <div />
      </SettingsLayout>,
    );
    // Same SR-visible behaviour as the old tabs — now as <nav> Links.
    expect(screen.getByRole("link", { name: /profile/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /notifications/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /appearance/i })).toBeInTheDocument();
    // New routes added in I-3:
    // WHY no security assertion: Security link is hidden when
    // NEXT_PUBLIC_ENABLE_SECURITY is not "true" (test env has it unset).
    expect(screen.getByRole("link", { name: /data/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /integrations/i })).toBeInTheDocument();
  });

  it("marks the active route via aria-current", () => {
    // usePathname mocked above to /settings/profile.
    render(
      <SettingsLayout>
        <div />
      </SettingsLayout>,
    );
    const profileLink = screen.getByRole("link", { name: /profile/i });
    expect(profileLink).toHaveAttribute("aria-current", "page");
  });
});

// ── Per-route page tests ───────────────────────────────────────────────────

describe("SettingsProfilePage", () => {
  it("renders the user email from useAuth", () => {
    render(<SettingsProfilePage />);
    expect(screen.getAllByText("test@example.com").length).toBeGreaterThan(0);
  });

  it("renders the user name", () => {
    render(<SettingsProfilePage />);
    expect(screen.getAllByText("Test User").length).toBeGreaterThan(0);
  });
});

describe("SettingsNotificationsPage", () => {
  it("renders notification preference switches", async () => {
    render(<SettingsNotificationsPage />, { wrapper: ({ children }) => wrap(children) });
    // WHY waitFor: the page shows skeletons during the prefs query; switches
    // appear once the query resolves (mocked to return null → defaults render).
    await waitFor(() => {
      const switches = screen.getAllByRole("switch");
      expect(switches.length).toBeGreaterThan(0);
    });
  });

  it("renders the notification preferences description", async () => {
    // WHY updated: W8 replaced the 'coming soon' placeholder with real switches.
    // The description text confirms the form is fully wired to the API.
    render(<SettingsNotificationsPage />, { wrapper: ({ children }) => wrap(children) });
    await waitFor(() => {
      expect(screen.getByText(/changes are saved immediately/i)).toBeInTheDocument();
    });
  });
});

describe("SettingsAppearancePage", () => {
  it("renders the dark-mode 'permanently enabled' explanation", () => {
    render(<SettingsAppearancePage />);
    expect(screen.getByText(/permanently enabled/i)).toBeInTheDocument();
  });

  it("renders the color palette swatches", () => {
    render(<SettingsAppearancePage />);
    // Each swatch is a button with the "Copy <name> hex value..." aria-label.
    const swatchButtons = screen.getAllByRole("button", { name: /copy .* hex value/i });
    expect(swatchButtons.length).toBeGreaterThan(0);
  });
});

// PLAN-0087 F-BB-005: Security page is no longer a placeholder. It now ships
// real (mocked-state) controls — MFA toggle, password form, sessions list,
// audit log. We assert on the substantive content.
describe("SettingsSecurityPage", () => {
  // WHY set env var: security page calls notFound() unless
  // NEXT_PUBLIC_ENABLE_SECURITY="true". These tests verify the page content
  // so they must enable the feature flag for the duration of each test.
  beforeEach(() => {
    process.env.NEXT_PUBLIC_ENABLE_SECURITY = "true";
  });
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_ENABLE_SECURITY;
  });

  it("renders the two-factor authentication card", () => {
    render(<SettingsSecurityPage />);
    // The phrase appears in both the heading and body copy; assert presence
    // via getAllByText so either occurrence satisfies the check.
    expect(
      screen.getAllByText(/two-factor authentication/i).length,
    ).toBeGreaterThan(0);
  });

  it("renders the password change form", () => {
    render(<SettingsSecurityPage />);
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^new password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm new password/i)).toBeInTheDocument();
  });

  it("renders the active sessions list with at least one row", () => {
    render(<SettingsSecurityPage />);
    expect(screen.getByText(/active sessions/i)).toBeInTheDocument();
    // The mock data includes at least one session marked as the current device.
    expect(screen.getAllByText(/this device/i).length).toBeGreaterThan(0);
  });

  it("renders the recent sign-in audit list", () => {
    render(<SettingsSecurityPage />);
    expect(screen.getByText(/recent sign-ins/i)).toBeInTheDocument();
  });
});

// ── 404 not-found page tests (unchanged) ───────────────────────────────────

describe("NotFoundPage", () => {
  it("renders the 404 not found heading", () => {
    render(<NotFoundPage />);
    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
  });

  it("renders the Error 404 label", () => {
    render(<NotFoundPage />);
    expect(screen.getByText(/error 404/i)).toBeInTheDocument();
  });

  it("renders a link back to the dashboard", () => {
    render(<NotFoundPage />);
    const dashboardLink = screen.getByRole("link", { name: /back to dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");
  });

  it("renders a link to the home page", () => {
    render(<NotFoundPage />);
    const homeLink = screen.getByRole("link", { name: /go to home/i });
    expect(homeLink).toBeInTheDocument();
    expect(homeLink).toHaveAttribute("href", "/");
  });
});

// ── Error boundary page tests (unchanged) ──────────────────────────────────

describe("ErrorPage", () => {
  const mockError = new Error("Test error") as Error & { digest?: string };
  const mockReset = vi.fn();

  beforeEach(() => {
    mockReset.mockClear();
  });

  it("renders the error heading", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    expect(
      screen.getByRole("heading", { name: /unexpected error/i }),
    ).toBeInTheDocument();
  });

  it("renders the error message description", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    expect(screen.getByText(/unexpected error occurred/i)).toBeInTheDocument();
  });

  it("renders the Try again button", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    const retryButton = screen.getByRole("button", { name: /try again/i });
    expect(retryButton).toBeInTheDocument();
  });

  it("calls reset() when Try again is clicked", async () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    const user = userEvent.setup();
    const retryButton = screen.getByRole("button", { name: /try again/i });
    await user.click(retryButton);
    expect(mockReset).toHaveBeenCalledOnce();
  });

  it("renders a link back to the dashboard", () => {
    render(<ErrorPage error={mockError} reset={mockReset} />);
    const dashboardLink = screen.getByRole("link", { name: /back to dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");
  });
});
