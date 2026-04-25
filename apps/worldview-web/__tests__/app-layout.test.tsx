/**
 * __tests__/app-layout.test.tsx — Unit tests for the (app) route group auth guard
 *
 * WHY THIS EXISTS: The (app)/layout.tsx is the auth gate for every protected page
 * (Dashboard, Workspace, Portfolio, Chat, Screener, Alerts, Settings). It must:
 * 1. Block rendering and show a loading state while auth is being checked
 * 2. Redirect unauthenticated users to /login with a redirect_to param
 * 3. Render the full shell (TopBar + Sidebar + children) when authenticated
 *
 * WHY mock shell components: TopBar/Sidebar/FlashOverlay import heavyweight
 * dependencies — lightweight-charts (WebGL canvas), react-grid-layout, cmdk.
 * These don't work in jsdom and would make this a broader integration test.
 * Mocking them as minimal stubs isolates the auth guard logic under test.
 *
 * WHO USES IT: All protected routes — any bug here locks out every user or
 * exposes protected content, making this one of the highest-stakes tests.
 * DATA SOURCE: AuthContext via useAuth() hook (mocked here)
 * DESIGN REFERENCE: PRD-0028 §6.6.1 Auth Guard, app/(app)/layout.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

// ── Shell component mocks ─────────────────────────────────────────────────────
// WHY register mocks before the component import: Vitest hoists all vi.mock()
// calls above import statements at transform time, so these registrations are
// active before AppLayout (and its transitive deps) are loaded.

vi.mock("@/components/shell/TopBar", () => ({
  // WHY accept rest props without typing: TopBar receives onOpenAskAi + unreadAlerts.
  // Using a catch-all avoids TypeScript errors when mock doesn't match the full interface.
  TopBar: (props: Record<string, unknown>) => (
    <div data-testid="shell-topbar" data-unread-alerts={String(props.unreadAlerts ?? 0)} />
  ),
}));

// WHY CollapsibleSidebar (not Sidebar): layout.tsx now uses CollapsibleSidebar
// (PRD-0031 Wave 1). The mock accepts expanded/onToggle props without typing them
// strictly so it remains valid as the prop interface evolves.
vi.mock("@/components/shell/CollapsibleSidebar", () => ({
  CollapsibleSidebar: (props: Record<string, unknown>) => (
    <nav data-testid="shell-sidebar" data-expanded={String(props.expanded ?? true)} />
  ),
}));

vi.mock("@/components/shell/FlashOverlay", () => ({
  // WHY return null: FlashOverlay is a portal overlay. Rendering null in tests
  // avoids any portal-related jsdom edge cases while still importing correctly.
  FlashOverlay: () => null,
}));

// WHY mock WorkspaceProvider: WorkspaceProvider reads localStorage on mount.
// Mocking it to pass children through avoids localStorage dependency in auth tests.
vi.mock("@/contexts/WorkspaceContext", () => ({
  WorkspaceProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useWorkspace: vi.fn(() => ({
    workspaces: [],
    activeWorkspaceId: "ws-1",
    activeWorkspace: undefined,
    setActiveWorkspace: vi.fn(),
    addWorkspace: vi.fn(),
    removeWorkspace: vi.fn(),
    renameWorkspace: vi.fn(),
  })),
}));

// ── AlertStreamContext mock ───────────────────────────────────────────────────
// WHY: AlertStreamProvider opens a WebSocket to S10 on mount. In unit tests
// this would either fail (no server) or require complex WS mocking. The mock
// provider passes children through; useAlertStream returns an empty alert state.
vi.mock("@/contexts/AlertStreamContext", () => ({
  AlertStreamProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAlertStream: vi.fn(() => ({
    unreadCount: 0,
    criticalQueue: [],
    recentAlerts: [],
    dequeueCritical: vi.fn(),
  })),
}));

// ── Next.js navigation mock ───────────────────────────────────────────────────
// WHY: AppLayout calls router.replace() when unauthenticated — the App Router
// context is not available in jsdom, so useRouter() must be mocked.
const mockRouterReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    replace: mockRouterReplace,
    push: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/dashboard"),
}));

// ── Auth hook mock ────────────────────────────────────────────────────────────
// WHY vi.hoisted (not plain vi.fn()): vi.mock factories are hoisted above ALL
// module-level code by Vitest's Vite transform, including `const` declarations.
// A plain `const mockUseAuth = vi.fn()` would be in the Temporal Dead Zone when
// the factory runs, causing "Cannot access before initialization". vi.hoisted()
// creates the variable BEFORE the module evaluation order, so it is always
// defined when the factory body executes.
// See: https://vitest.dev/api/vi.html#vi-hoisted
const mockUseAuth = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useAuth", () => ({
  useAuth: mockUseAuth,
}));

// ── Component under test ──────────────────────────────────────────────────────
// Static import works here because vi.mock() calls above are hoisted by Vitest's
// Vite transform to run before any import statement resolves.
import AppLayout from "@/app/(app)/layout";

// ── Test setup ────────────────────────────────────────────────────────────────

// WHY localStorage stub: layout.tsx reads localStorage in its useState lazy initializer
// for the sidebar expanded state. jsdom's localStorage may not expose all methods
// (BP-160 pattern). Stubbing gives us full control and consistent behavior.
const localStorageMock = {
  getItem: vi.fn(() => null as string | null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(() => null as string | null),
};

beforeEach(() => {
  vi.clearAllMocks();
  // WHY stubGlobal: makes localStorage available with the mock implementation
  // for all code that runs during these tests, including the layout lazy initializer.
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
  localStorageMock.getItem.mockReturnValue(null);

  // WHY re-set after clearAllMocks: clearAllMocks() resets mockUseAuth to return
  // undefined. We need a predictable default so tests that don't override the
  // return value don't get undefined and crash with "Cannot destructure undefined".
  mockUseAuth.mockReturnValue({
    isLoading: false,
    isAuthenticated: false,
    accessToken: null,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  });
  // Also re-seed the router replace fn since clearAllMocks() cleared it
  mockRouterReplace.mockReset();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AppLayout — auth guard", () => {
  it("shows loading spinner while auth check is in progress", () => {
    /**
     * On page load, AuthProvider fires POST /auth/refresh silently.
     * Until that resolves, isLoading=true. The layout must render a spinner
     * instead of protected content — preventing a flash of unauthenticated state.
     */
    mockUseAuth.mockReturnValue({
      isLoading: true,
      isAuthenticated: false,
      accessToken: null,
      user: null,
      setTokens: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <AppLayout>
        <div data-testid="protected-child">Protected Content</div>
      </AppLayout>,
    );

    // WHY check for "Initializing session" text: matches the exact spinner copy
    // in the layout — if the copy changes, this test catches the regression.
    expect(screen.getByText(/Initializing session/i)).toBeInTheDocument();

    // Protected content must NOT render during loading — avoids unauthorized API calls
    expect(screen.queryByTestId("protected-child")).not.toBeInTheDocument();
  });

  it("redirects unauthenticated users to /login with redirect_to param", async () => {
    /**
     * After the auth check completes (isLoading=false), if the user has no
     * valid session (isAuthenticated=false), the layout redirects to /login.
     * The redirect_to param encodes the current path so the user returns to
     * their intended destination after logging in.
     */
    mockUseAuth.mockReturnValue({
      isLoading: false,
      isAuthenticated: false,
      accessToken: null,
      user: null,
      setTokens: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <AppLayout>
        <div data-testid="protected-child">Sensitive Data</div>
      </AppLayout>,
    );

    // Wait for the useEffect to fire (runs after render, calls router.replace())
    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    });

    // WHY check for /login?redirect_to=: The redirect must preserve destination.
    // Without redirect_to, users land on the dashboard after login regardless of
    // where they were going — bad UX for direct links and bookmarks.
    const redirectArg = mockRouterReplace.mock.calls[0][0] as string;
    expect(redirectArg).toMatch(/^\/login\?redirect_to=/);

    // Protected content must not render before redirect completes
    expect(screen.queryByTestId("protected-child")).not.toBeInTheDocument();
  });

  it("renders protected shell and children when user is authenticated", () => {
    /**
     * Authenticated users see the full terminal: TopBar (for market status,
     * alerts badge, user menu), Sidebar (for navigation), and the page content.
     * The auth guard renders its children when isAuthenticated=true.
     */
    mockUseAuth.mockReturnValue({
      isLoading: false,
      isAuthenticated: true,
      accessToken: "eyJhbGciOiJSUzI1NiJ9.test.signature",
      user: {
        user_id: "user-001",
        tenant_id: "tenant-001",
        email: "trader@fund.com",
        name: "Trader One",
        avatar_url: null,
      },
      setTokens: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <AppLayout>
        <div data-testid="protected-child">Dashboard Content</div>
      </AppLayout>,
    );

    // Shell components must be mounted (TopBar provides market status + nav)
    expect(screen.getByTestId("shell-topbar")).toBeInTheDocument();
    expect(screen.getByTestId("shell-sidebar")).toBeInTheDocument();

    // Protected page content must render for authenticated users
    expect(screen.getByTestId("protected-child")).toBeInTheDocument();
    expect(screen.getByText("Dashboard Content")).toBeInTheDocument();

    // No redirect — authenticated users stay on the page
    expect(mockRouterReplace).not.toHaveBeenCalled();
  });
});
