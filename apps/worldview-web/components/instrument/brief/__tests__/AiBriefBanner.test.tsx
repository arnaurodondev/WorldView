/**
 * components/instrument/brief/__tests__/AiBriefBanner.test.tsx
 *
 * WHY THIS EXISTS: AiBriefBanner is the collapsible AI brief between the
 * instrument header and tab bar (PRD-0088 §6.5). Wave-2 redesigned it from a
 * raw-markdown dump into a parsed lead + rendered-markdown block — this suite
 * PORTS the four original contracts and ADDS the redesign's rendering pins:
 *
 *  PORTED (from the pre-redesign suite — coverage must not shrink, R19):
 *   1. hides entirely when the brief is null (no reserved space);
 *   2. expands on first click / collapses on second (aria-expanded);
 *   3. persists collapse state to sessionStorage keyed by entityId;
 *   4. hydrates from sessionStorage='expanded' on mount.
 *
 *  NEW (Wave-2 redesign):
 *   5. the collapsed strip shows the parsed LEAD — never the raw "## LEAD"
 *      hashes or "[cN]" citation tokens (THE markdown-rendering bug);
 *   6. expanding renders the DETAILS as real markdown (an <h3> element from
 *      "### Recent Developments", not literal hashes);
 *   7. Discuss links to /chat?entity_id=…; Regenerate POSTs the lazy-generate
 *      trigger and disables itself while queued;
 *   8. briefs older than 24h show the amber STALE tag.
 *
 * MOCK STRATEGY: gateway mocked at its seam (getInstrumentBrief +
 * triggerInstrumentBriefingGeneration); useAuth mocked for a token; fresh
 * QueryClient per test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// WHY per-test mock of gateway: each scenario needs a different return value.
const mockGateway = vi.hoisted(() => ({
  getInstrumentBrief: vi.fn(),
  triggerInstrumentBriefingGeneration: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// IMPORTANT: import the component AFTER vi.mock calls so the mocks are wired.
// eslint-disable-next-line import/first
import { AiBriefBanner } from "@/components/instrument/brief/AiBriefBanner";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Minimal valid BriefingResponse — only the fields the banner reads. */
function fakeBrief(narrative: string, generatedAt: string = new Date().toISOString()) {
  return {
    narrative,
    generated_at: generatedAt,
    cached: false,
    entity_id: "ent-001",
    risk_summary: null,
    citations: [],
  };
}

/** Live-shaped structured narrative (the format S8 actually emits). */
const STRUCTURED = [
  "## LEAD",
  "Apple's WWDC26 Siri AI rollout marks a critical step. [c6][c7]",
  "",
  "---",
  "",
  "## DETAILS",
  "### Recent Developments",
  "- [2026-06-08] Apple unveiled Siri AI at WWDC26. [c6]",
].join("\n");

/** The toggle is the only button carrying aria-expanded (actions don't). */
function getToggle(): HTMLElement {
  const btn = screen
    .getAllByRole("button")
    .find((b) => b.hasAttribute("aria-expanded"));
  if (!btn) throw new Error("toggle button not found");
  return btn;
}

beforeEach(() => {
  mockGateway.getInstrumentBrief.mockReset();
  mockGateway.triggerInstrumentBriefingGeneration.mockReset();
  window.sessionStorage.clear();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("AiBriefBanner", () => {
  // ── Ported contract 1 ──────────────────────────────────────────────────────
  it("renders nothing when the brief is null (banner hidden entirely)", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(null);
    const { container } = render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });

  // ── Ported contract 2 ──────────────────────────────────────────────────────
  it("expands on first click and collapses on second click", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Apple beat EPS by 5c on iPhone strength."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => getToggle());
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(toggleButton);
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");
  });

  // ── Ported contract 3 ──────────────────────────────────────────────────────
  it("persists collapse state to sessionStorage keyed by entityId", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Some narrative content here."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => getToggle());
    fireEvent.click(toggleButton);
    expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("expanded");
    fireEvent.click(toggleButton);
    expect(window.sessionStorage.getItem("wv:brief-collapsed:ent-001")).toBe("collapsed");
  });

  // ── Ported contract 4 ──────────────────────────────────────────────────────
  it("hydrates from sessionStorage='expanded' on mount", async () => {
    window.sessionStorage.setItem("wv:brief-collapsed:ent-001", "expanded");
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief("Persisted-expanded narrative."));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => getToggle());
    await waitFor(() => {
      expect(toggleButton).toHaveAttribute("aria-expanded", "true");
    });
  });

  // ── NEW: markdown rendering (THE Wave-2 bug) ──────────────────────────────
  it("collapsed strip shows the parsed LEAD — no raw '## LEAD' or [cN] tokens", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief(STRUCTURED));
    const { container } = render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    await waitFor(() => getToggle());
    // The LEAD sentence is visible…
    expect(
      screen.getByText(/Apple's WWDC26 Siri AI rollout marks a critical step\./),
    ).toBeInTheDocument();
    // …but the markdown chrome and citation tokens are NOT.
    expect(container.textContent).not.toContain("## LEAD");
    expect(container.textContent).not.toContain("[c6]");
  });

  it("expanding renders DETAILS as real markdown (h3 element, no literal hashes)", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief(STRUCTURED));
    const { container } = render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => getToggle());
    fireEvent.click(toggleButton);

    // "### Recent Developments" must arrive as a REAL heading element…
    const h3 = await waitFor(() => screen.getByRole("heading", { level: 3 }));
    expect(h3).toHaveTextContent("Recent Developments");
    // …and no literal hash chrome anywhere in the expanded body.
    expect(container.textContent).not.toContain("###");
    expect(container.textContent).not.toContain("## DETAILS");
  });

  // ── NEW: actions ───────────────────────────────────────────────────────────
  it("expanded footer links Discuss to /chat?entity_id=… and Regenerate POSTs the trigger", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief(STRUCTURED));
    mockGateway.triggerInstrumentBriefingGeneration.mockResolvedValue(undefined);
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    const toggleButton = await waitFor(() => getToggle());
    fireEvent.click(toggleButton);

    // Discuss deep-link carries the entity id for chat context seeding.
    const discuss = screen.getByRole("link", { name: /discuss/i });
    expect(discuss).toHaveAttribute("href", "/chat?entity_id=ent-001");

    // Regenerate fires the idempotent lazy-generate POST and flips to the
    // queued (disabled) state so a double-click cannot double-queue.
    const regen = screen.getByRole("button", { name: /regenerate/i });
    fireEvent.click(regen);
    await waitFor(() => {
      expect(mockGateway.triggerInstrumentBriefingGeneration).toHaveBeenCalledWith("ent-001");
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /queued/i })).toBeDisabled();
    });
  });

  // ── NEW: staleness ─────────────────────────────────────────────────────────
  it("shows the amber STALE tag for briefs older than 24h", async () => {
    const old = new Date(Date.now() - 36 * 60 * 60 * 1000).toISOString();
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief(STRUCTURED, old));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    await waitFor(() => getToggle());
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  it("does NOT show the STALE tag for a fresh brief", async () => {
    mockGateway.getInstrumentBrief.mockResolvedValue(fakeBrief(STRUCTURED));
    render(
      <Wrapper>
        <AiBriefBanner entityId="ent-001" />
      </Wrapper>,
    );
    await waitFor(() => getToggle());
    expect(screen.queryByText(/^stale$/i)).not.toBeInTheDocument();
  });
});
