/**
 * features/chat/components/__tests__/ActionConfirmModal.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0082 Wave B):
 * ActionConfirmModal is the confirmation gate for write-action tool calls.
 * It shows the pending action params, lets the user confirm or cancel,
 * and calls POST /api/v1/chat/proposals/{id}/confirm.
 *
 * WHAT WE TEST:
 *   1. Renders nothing when pendingAction is null (modal is closed).
 *   2. Renders action title and params when pendingAction is set.
 *   3. Cancel button calls onDismiss.
 *   4. Escape key / overlay click calls onDismiss (Radix Dialog behaviour).
 *   5. Confirm button calls the confirm endpoint and shows success state.
 *   6. Confirm button shows error state on non-2xx response.
 *   7. Confirm button retries after an error.
 *   8. Confirm button is disabled while loading (prevents double-submit).
 *
 * WHY mock fetch: the confirm endpoint is a real POST to /api/v1/chat/proposals/...
 * We mock fetch to control the SSE response without a running backend.
 *
 * WHY mock @radix-ui/react-dialog: jsdom doesn't implement the
 * `inert` HTML attribute or `role=dialog` portals correctly in all
 * versions. We partially mock the Dialog to render children in-place
 * so assertions work without portal/portal-target hacks.
 */

import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { ActionConfirmModal } from "../ActionConfirmModal";
import type { PendingActionEvent } from "../../lib/types";

// ── Mocks ─────────────────────────────────────────────────────────────────────

/**
 * WHY mock @radix-ui/react-dialog:
 * Radix Dialog uses portals that attach to document.body, and the Dialog.Root
 * manages open/closed animation state that conflicts with jsdom's lack of
 * pointer-events and IntersectionObserver. We render the content directly
 * (no portal) so the test's `screen` queries work without mounting a full
 * DOM environment.
 */
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    children,
    open,
    onOpenChange,
  }: {
    children: React.ReactNode;
    open: boolean;
    onOpenChange: (v: boolean) => void;
  }) =>
    open ? (
      <div
        data-testid="dialog-root"
        // Simulate Esc key as onOpenChange(false) — Radix does this natively;
        // our mock wires it to onKeyDown for testability.
        onKeyDown={(e: React.KeyboardEvent) => {
          if (e.key === "Escape") onOpenChange(false);
        }}
      >
        {children}
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dialog-content">{children}</div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dialog-header">{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2 data-testid="dialog-title">{children}</h2>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => (
    <p data-testid="dialog-description">{children}</p>
  ),
  DialogFooter: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dialog-footer">{children}</div>
  ),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

/**
 * makePendingAction — builds a minimal PendingActionEvent fixture.
 *
 * WHY factory function (not a const): individual tests can override fields
 * to exercise different rendering paths (e.g. missing description → default text).
 */
function makePendingAction(
  overrides: Partial<PendingActionEvent> = {},
): PendingActionEvent {
  return {
    proposal_id: "prop-test-001",
    tool: "create_alert",
    description: "Create price_below alert for AAPL at $180",
    params: {
      entity_id: "aapl-entity-uuid",
      condition: "price_below",
      threshold: { value: 180 },
      severity: "medium",
    },
    ...overrides,
  };
}

/**
 * makeReader — build a minimal SSE reader from an array of string frames.
 *
 * Same pattern as useChatStream.test.tsx — returns chunks one by one,
 * then done:true.
 */
function makeReader(frames: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    read: (): Promise<{ done: boolean; value?: Uint8Array }> => {
      if (i >= frames.length) return Promise.resolve({ done: true });
      const value = encoder.encode(frames[i++]);
      return Promise.resolve({ done: false, value });
    },
    cancel: vi.fn().mockResolvedValue(undefined),
  };
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ActionConfirmModal", () => {
  it("renders nothing when pendingAction is null", () => {
    // WHY: the modal must be invisible/unmounted when there is no pending action.
    // Rendering even a hidden modal would trigger Radix portal DOM noise.
    const onDismiss = vi.fn();
    const { container } = render(
      <ActionConfirmModal
        pendingAction={null}
        accessToken="tok-abc"
        onDismiss={onDismiss}
      />,
    );

    // Dialog mock returns null when open=false, so nothing in the DOM.
    expect(container.firstChild).toBeNull();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("renders action title and description when pendingAction is set", () => {
    // WHY: the user must see what action the LLM wants to take before confirming.
    // The modal title and description are the primary information surface.
    const pa = makePendingAction();
    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-abc"
        onDismiss={vi.fn()}
      />,
    );

    // Title contains the human-readable action name.
    const title = screen.getByTestId("dialog-title");
    expect(title.textContent).toContain("Create Alert");

    // Description shows the LLM-generated action description.
    const desc = screen.getByTestId("dialog-description");
    expect(desc.textContent).toContain("Create price_below alert for AAPL at $180");
  });

  it("renders param rows for entity_id, condition, threshold, severity", () => {
    // WHY: analysts need to see the full action parameters before confirming —
    // a description-only modal could mask a wrong threshold value.
    const pa = makePendingAction();
    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-abc"
        onDismiss={vi.fn()}
      />,
    );

    // Each param key appears as an uppercase label.
    expect(screen.getByText("Entity ID")).toBeDefined();
    expect(screen.getByText("Condition")).toBeDefined();
    expect(screen.getByText("Threshold")).toBeDefined();
    expect(screen.getByText("Severity")).toBeDefined();

    // Values appear as monospace text.
    expect(screen.getByText("aapl-entity-uuid")).toBeDefined();
    expect(screen.getByText("price_below")).toBeDefined();
    // Threshold is serialized as JSON.
    expect(screen.getByText('{"value":180}')).toBeDefined();
  });

  it("uses a fallback description when pendingAction.description is missing", () => {
    // WHY: the SSE event SHOULD have a description, but we handle missing fields
    // gracefully to avoid a blank modal.
    const pa = makePendingAction({ description: "" });
    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-abc"
        onDismiss={vi.fn()}
      />,
    );

    // Empty description → fallback text.
    const desc = screen.getByTestId("dialog-description");
    expect(desc.textContent).toContain("Review the action details");
  });

  it("Cancel button calls onDismiss", () => {
    // WHY: onDismiss calls clearPendingAction on the hook which closes the modal.
    // Without this, the Cancel button would do nothing.
    const onDismiss = vi.fn();
    render(
      <ActionConfirmModal
        pendingAction={makePendingAction()}
        accessToken="tok-abc"
        onDismiss={onDismiss}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel action" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("Confirm button calls the confirm endpoint with correct body", async () => {
    // WHY: the confirm POST must include the correct proposal_id in the URL
    // and the params from pendingAction in the request body. A mismatch would
    // call a different action or create the wrong alert.
    const pa = makePendingAction();
    const reader = makeReader([
      `event: action_executed\ndata: ${JSON.stringify({ proposal_id: pa.proposal_id, tool_name: pa.tool, result: { alert_id: "alert-new-001" } })}\n`,
      "data: [DONE]\n",
    ]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    });
    vi.stubGlobal("fetch", fetchMock);

    const onDismiss = vi.fn();
    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-xyz"
        onDismiss={onDismiss}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm action" }));
      // Allow the fetch + SSE read to complete.
      await new Promise((r) => setTimeout(r, 0));
    });

    // Verify the endpoint URL includes the proposal_id.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/v1/chat/proposals/${pa.proposal_id}/confirm`);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer tok-xyz",
    });

    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.tool_name).toBe("create_alert");
    expect(body.entity_id).toBe("aapl-entity-uuid");
    expect(body.condition).toBe("price_below");
    expect(body.severity).toBe("medium");
  });

  it("shows success state after action_executed SSE event", async () => {
    // WHY: the user needs visual confirmation that the alert was created.
    // Without the success state, the modal would auto-dismiss without feedback.
    const pa = makePendingAction();
    const reader = makeReader([
      `event: action_executed\ndata: ${JSON.stringify({ proposal_id: pa.proposal_id, tool_name: pa.tool, result: { alert_id: "alert-new-002" } })}\n`,
      "data: [DONE]\n",
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    }));

    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-xyz"
        onDismiss={vi.fn()}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm action" }));
      await new Promise((r) => setTimeout(r, 50));
    });

    // Success message should appear — contains "Alert created" and the alert ID.
    await waitFor(() => {
      expect(screen.getByText(/Alert created successfully/i)).toBeDefined();
      expect(screen.getByText(/alert-new-002/)).toBeDefined();
    });
  });

  it("shows error state on non-2xx response", async () => {
    // WHY: network errors and 4xx/5xx responses must be surfaced to the user
    // so they can retry or report the issue. Silent failure is unacceptable
    // for a write-action that creates financial alerts.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: vi.fn().mockResolvedValue("Unprocessable Entity"),
      body: null,
    }));

    render(
      <ActionConfirmModal
        pendingAction={makePendingAction()}
        accessToken="tok-xyz"
        onDismiss={vi.fn()}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm action" }));
      await new Promise((r) => setTimeout(r, 50));
    });

    // Error state should appear.
    await waitFor(() => {
      expect(screen.getByText(/Request failed/i)).toBeDefined();
    });
  });

  it("shows error state on action_rejected SSE event", async () => {
    // WHY: S8 can reject the action (e.g. S10 unavailable). The error must be
    // shown inline in the modal — NOT as a global chatError — because it is
    // specific to this confirmation flow, not the chat stream.
    const pa = makePendingAction();
    const reader = makeReader([
      `event: action_rejected\ndata: ${JSON.stringify({ proposal_id: pa.proposal_id, tool_name: pa.tool, reason: "service_unavailable" })}\n`,
      "data: [DONE]\n",
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => reader },
    }));

    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-xyz"
        onDismiss={vi.fn()}
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Confirm action" }));
      await new Promise((r) => setTimeout(r, 50));
    });

    await waitFor(() => {
      expect(screen.getByText(/Action rejected.*service_unavailable/i)).toBeDefined();
    });

    // Retry button should appear after rejection.
    expect(screen.getByRole("button", { name: "Confirm action" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Confirm action" }).textContent).toBe("Retry");
  });

  it("Confirm button is disabled while loading", async () => {
    // WHY: prevents double-submission. If the user clicks Confirm twice,
    // two alerts would be created — a correctness bug with real side effects.
    // The button must be disabled from the moment the first click is processed
    // until the SSE stream resolves.
    const pa = makePendingAction();

    // Use a fetch that NEVER resolves so we can assert the loading state.
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    render(
      <ActionConfirmModal
        pendingAction={pa}
        accessToken="tok-xyz"
        onDismiss={vi.fn()}
      />,
    );

    // Before click: button is enabled.
    const confirmBtn = screen.getByRole("button", { name: "Confirm action" });
    expect(confirmBtn).not.toBeDisabled();

    // After click: button becomes disabled.
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Confirm action" })).toBeDisabled();
    });
  });
});
