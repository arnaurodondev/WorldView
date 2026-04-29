/**
 * __tests__/workspace-share.test.tsx — Tests for ShareWorkspaceDialog
 *
 * WHY THIS EXISTS: ShareWorkspaceDialog is a thin UI wrapper around the
 * encode/decode logic in lib/workspace-share.ts. The dialog must:
 *   1. Render the encoded URL when given a valid workspace
 *   2. Call navigator.clipboard.writeText when Copy is clicked
 *   3. Show an error banner if the encoded token exceeds MAX_TOKEN_CHARS
 *
 * Encoder/decoder UNIT tests live in workspace-share-lib.test.ts (sister file).
 * This file focuses on the COMPONENT behavior end-to-end.
 *
 * WHY MOCK navigator.clipboard: jsdom's clipboard mock is unreliable across
 * versions. We stub it with a vi.fn so we can assert against writeText calls
 * deterministically.
 *
 * COVERAGE:
 *   - Dialog opens and shows the URL field for a small workspace
 *   - URL contains the workspace's name encoded into the query param
 *   - Copy button writes the URL to navigator.clipboard
 *   - Oversize workspace shows the error banner instead of the URL
 *
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-07
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ShareWorkspaceDialog } from "@/components/workspace/ShareWorkspaceDialog";
import {
  decodeWorkspace,
  encodeWorkspace,
  MAX_TOKEN_CHARS,
} from "@/lib/workspace-share";
import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── Sample workspace fixtures ────────────────────────────────────────────────

const SMALL_WORKSPACE: WorkspaceConfig = {
  id: "ws-test",
  name: "Test Workspace",
  rows: [
    { panels: [{ id: "p-1", type: "chart" }, { id: "p-2", type: "news" }] },
  ],
};

/**
 * makeOversizeWorkspace — generates a workspace whose encoded token EXCEEDS
 * MAX_TOKEN_CHARS. We construct it by adding many panels with long ids.
 *
 * WHY this approach: a real workspace can't realistically reach 4KB of JSON
 * (panels are tiny), so we synthesize one with deliberately-padded panel ids
 * to trigger the oversize path. Tests against synthetic inputs are still
 * legitimate because the encoder doesn't care WHY the input is large.
 */
function makeOversizeWorkspace(): WorkspaceConfig {
  // WHY 800 panels with ~10 char names: 800 * (id 60 chars + type 10 chars + JSON overhead 12) = ~65K
  // chars of JSON, which when base64-encoded grows by ~33% to ~87K — well above MAX_TOKEN_CHARS.
  const longId = "panel-with-an-intentionally-long-id-suffix-".repeat(2);
  const panels = Array.from({ length: 800 }, (_, i) => ({
    id: `${longId}${i}`,
    type: "chart" as const,
  }));
  return {
    id: "ws-large",
    name: "Large Workspace",
    rows: [{ panels }],
  };
}

// ── Clipboard mock ────────────────────────────────────────────────────────────
// WHY mockClipboardWrite returned promise: navigator.clipboard.writeText
// returns a promise; the dialog awaits it. A non-promise mock would surface
// as "writeText is not async" warnings.
const mockClipboardWrite = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  mockClipboardWrite.mockClear();
  // WHY Object.defineProperty (not a simple stubGlobal): navigator is a
  // read-only host object in jsdom; you can't reassign navigator.clipboard
  // directly. defineProperty with configurable:true is the standard escape.
  Object.defineProperty(window.navigator, "clipboard", {
    value: { writeText: mockClipboardWrite },
    writable: true,
    configurable: true,
  });
  // WHY stub window.location.origin: the dialog uses window.location.origin
  // for the share URL. jsdom returns "http://localhost" by default which is
  // fine, but we stabilize for clarity.
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("ShareWorkspaceDialog — small workspace", () => {
  it("opens the dialog and renders the URL field", async () => {
    const user = userEvent.setup();
    render(<ShareWorkspaceDialog config={SMALL_WORKSPACE} />);

    await user.click(screen.getByRole("button", { name: /share this workspace/i }));

    // WHY findByTestId: dialog mounts asynchronously via Radix portal.
    const urlInput = await screen.findByTestId("share-url-input");
    expect(urlInput).toBeInTheDocument();
  });

  it("URL field contains the encoded workspace token", async () => {
    const user = userEvent.setup();
    render(<ShareWorkspaceDialog config={SMALL_WORKSPACE} />);

    await user.click(screen.getByRole("button", { name: /share this workspace/i }));

    const urlInput = (await screen.findByTestId("share-url-input")) as HTMLInputElement;
    // WHY decode + compare: rather than asserting the exact token (brittle to
    // encoding changes), decode the embedded token and verify it matches the
    // original workspace shape. This test is robust to encoder optimizations.
    const tokenMatch = urlInput.value.match(/[?&]config=([^&]+)/);
    expect(tokenMatch).not.toBeNull();
    const decoded = decodeWorkspace(tokenMatch![1]);
    expect(decoded?.name).toBe(SMALL_WORKSPACE.name);
    expect(decoded?.rows.length).toBe(SMALL_WORKSPACE.rows.length);
  });

  it("calls clipboard.writeText when Copy is clicked", async () => {
    // WHY fireEvent (not userEvent): userEvent v14 installs its OWN clipboard
    // wrapper in setup() that overrides our mock. fireEvent bypasses that
    // entirely — the click handler in our component reads navigator.clipboard
    // directly at click time, so our pre-installed mock is what gets called.
    const user = userEvent.setup();
    render(<ShareWorkspaceDialog config={SMALL_WORKSPACE} />);

    await user.click(screen.getByRole("button", { name: /share this workspace/i }));
    const copyButton = await screen.findByTestId("share-copy-button");

    // WHY re-stub navigator.clipboard right before the click: userEvent.setup
    // overrode our beforeEach stub. Re-stubbing here ensures our spy is the
    // one called by the component's handleCopy → navigator.clipboard.writeText.
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText: mockClipboardWrite },
      writable: true,
      configurable: true,
    });
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(mockClipboardWrite).toHaveBeenCalledTimes(1);
    });
    // WHY assert URL shape: the call argument should be the URL containing the
    // ?config= token. Substring match is sufficient.
    expect(mockClipboardWrite.mock.calls[0][0]).toContain("/workspace?config=");
  });
});

describe("ShareWorkspaceDialog — oversize workspace", () => {
  it("shows the oversize error banner instead of the URL", async () => {
    const oversize = makeOversizeWorkspace();
    // WHY sanity-check the fixture: if the synthetic workspace doesn't actually
    // exceed MAX_TOKEN_CHARS, the test would silently pass for the wrong
    // reason. Asserting the precondition guards against that.
    expect(encodeWorkspace(oversize).length).toBeGreaterThan(MAX_TOKEN_CHARS);

    const user = userEvent.setup();
    render(<ShareWorkspaceDialog config={oversize} />);
    await user.click(screen.getByRole("button", { name: /share this workspace/i }));

    expect(
      await screen.findByText(/workspace too large to share via url/i),
    ).toBeInTheDocument();
    // The URL input should NOT appear in the oversize state
    expect(screen.queryByTestId("share-url-input")).toBeNull();
  });
});
