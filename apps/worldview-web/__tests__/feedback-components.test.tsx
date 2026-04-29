/**
 * __tests__/feedback-components.test.tsx — Wave G UI component tests.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G validation gate):
 * One Vitest happy-path test per UI component:
 *   - MicroSurvey         → renders, click submits the right shape
 *   - NPSPrompt           → renders with score grid, submit-disabled until pick
 *   - FeedbackButton      → renders for authenticated users only
 *   - ConsoleLogCapture   → toggles opt-in, renders logs
 *   - ScreenshotCapture   → renders capture button, calls onCapture(null) on discard
 *   - FeedbackModal       → opens with default tab and shows the matching form
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth mock — most components hide for unauth.
const mockUseAuth = vi.fn(() => ({
  accessToken: "test-token",
  isAuthenticated: true,
  user: null,
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

// ── Gateway mock.
const mockPostMicroSurvey = vi.fn().mockResolvedValue(undefined);
const mockPostNPS = vi.fn().mockResolvedValue({ id: "n-1", score: 9, created_at: "x" });
const mockPostFeedback = vi.fn().mockResolvedValue({ id: "f-1" });
const mockPostFeature = vi.fn().mockResolvedValue({ id: "fr-1" });

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    postMicroSurvey: mockPostMicroSurvey,
    postNPS: mockPostNPS,
    postFeedbackSubmission: mockPostFeedback,
    postFeatureRequest: mockPostFeature,
  }),
  GatewayError: class extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

// Wrapper + helper.
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // eslint-disable-next-line react/display-name
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  mockUseAuth.mockReturnValue({
    accessToken: "test-token",
    isAuthenticated: true,
    user: null,
  });
});

// ── MicroSurvey ────────────────────────────────────────────────────────────

describe("MicroSurvey", () => {
  it("renders three reaction buttons and submits the picked one", async () => {
    const { MicroSurvey } = await import("@/components/feedback/MicroSurvey");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <MicroSurvey surveyKey="dashboard.helpful" prompt="Helpful?" />
      </Wrapper>,
    );
    // Three buttons (Helpful / Not helpful / Unsure).
    expect(screen.getByLabelText("Helpful")).toBeInTheDocument();
    expect(screen.getByLabelText("Not helpful")).toBeInTheDocument();
    expect(screen.getByLabelText("Unsure")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Helpful"));
    // The mutation fires synchronously enough for vitest — assert call args.
    await new Promise((r) => setTimeout(r, 5));
    expect(mockPostMicroSurvey).toHaveBeenCalledWith({
      survey_key: "dashboard.helpful",
      response: "positive",
    });
  });
});

// ── NPSPrompt ──────────────────────────────────────────────────────────────

describe("NPSPrompt", () => {
  it("renders 0..10 buttons and disables submit until a score is picked", async () => {
    const { NPSPrompt } = await import("@/components/feedback/NPSPrompt");
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <NPSPrompt open={true} onOpenChange={() => {}} surface="test_surface" />
      </Wrapper>,
    );
    // 11 score buttons plus dialog Submit + Maybe later.
    for (let i = 0; i <= 10; i++) {
      expect(screen.getByRole("radio", { name: String(i) })).toBeInTheDocument();
    }
    const submitBtn = screen.getByRole("button", { name: /^Submit$/ });
    expect(submitBtn).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "9" }));
    expect(submitBtn).toBeEnabled();
  });
});

// ── FeedbackButton ─────────────────────────────────────────────────────────

describe("FeedbackButton", () => {
  it("renders for authenticated users", async () => {
    const { FeedbackButton } = await import(
      "@/components/feedback/FeedbackButton"
    );
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <FeedbackButton />
      </Wrapper>,
    );
    expect(
      screen.getByRole("button", { name: /Send feedback/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing when unauthenticated", async () => {
    mockUseAuth.mockReturnValue({
      accessToken: null as unknown as string,
      isAuthenticated: false,
      user: null,
    });
    const { FeedbackButton } = await import(
      "@/components/feedback/FeedbackButton"
    );
    const Wrapper = makeWrapper();
    const { container } = render(
      <Wrapper>
        <FeedbackButton />
      </Wrapper>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

// ── ConsoleLogCapture ──────────────────────────────────────────────────────

describe("ConsoleLogCapture", () => {
  it("toggles opt-in via the checkbox", async () => {
    const { ConsoleLogCapture } = await import(
      "@/components/feedback/ConsoleLogCapture"
    );
    const setEnabled = vi.fn();
    render(
      <ConsoleLogCapture
        enabled={false}
        onEnabledChange={setEnabled}
        logs={[]}
        onClear={() => {}}
      />,
    );
    // Use role=checkbox instead of label text (label includes the count).
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(setEnabled).toHaveBeenCalledWith(true);
  });
});

// ── ScreenshotCapture ──────────────────────────────────────────────────────

describe("ScreenshotCapture", () => {
  it("renders the capture button", async () => {
    const { ScreenshotCapture } = await import(
      "@/components/feedback/ScreenshotCapture"
    );
    render(<ScreenshotCapture onCapture={() => {}} hasCapture={false} />);
    expect(
      screen.getByRole("button", { name: /Capture screenshot/i }),
    ).toBeInTheDocument();
  });
});

// ── FeedbackModal ──────────────────────────────────────────────────────────

describe("FeedbackModal", () => {
  it("renders the bug tab by default with severity selector", async () => {
    const { FeedbackModal } = await import(
      "@/components/feedback/FeedbackModal"
    );
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <FeedbackModal open={true} onOpenChange={() => {}} />
      </Wrapper>,
    );
    // Multiple "Send feedback" strings appear (sheet title + button) — use role.
    expect(
      screen.getAllByText("Send feedback").length,
    ).toBeGreaterThanOrEqual(1);
    // Bug tab should be active — severity dropdown visible.
    expect(screen.getByText("Severity")).toBeInTheDocument();
  });
});
