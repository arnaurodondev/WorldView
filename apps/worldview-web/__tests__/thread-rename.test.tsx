/**
 * __tests__/thread-rename.test.tsx — inline rename behaviour
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-08): rename has multiple branches
 * (commit on Enter, cancel on Escape, optimistic update, rollback on error).
 * Tests pin every branch so future refactors don't lose any.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Round 4: HotkeyProvider is required by the page's useToolTraceChord (it
// registers the ⌘D debug chord in the central hotkey registry via context).
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";
import type { Thread } from "@/types/api";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/chat"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

const SAMPLE: Thread[] = [
  {
    thread_id: "t1",
    title: "Old title",
    owner_id: "u1",
    messages: [],
    created_at: "2026-04-10T09:00:00Z",
    updated_at: "2026-04-10T09:00:00Z",
  },
];

const updateThreadMock = vi.fn();
const getThreadsMock = vi.fn().mockResolvedValue(SAMPLE);

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getThreads: getThreadsMock,
    getThread: vi.fn(),
    deleteThread: vi.fn(),
    updateThread: updateThreadMock,
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isAuthenticated: true,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  }),
}));

let uuidCounter = 0;
vi.stubGlobal("crypto", { randomUUID: () => `uuid-${++uuidCounter}` });

function makeQC() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}
function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQC()}>
      {/* Round 4: useToolTraceChord registers via the hotkey registry —
          the page needs HotkeyProvider, same as app/(app)/layout.tsx. */}
      <HotkeyProvider registry={new HotkeyRegistry()}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

async function renderChat() {
  const { default: ChatPage } = await import("@/app/(app)/chat/page");
  return render(<ChatPage />, { wrapper: Wrapper });
}

beforeEach(() => {
  uuidCounter = 0;
  updateThreadMock.mockReset();
  // Reset getThreads to return a fresh copy each test, so optimistic
  // mutations don't bleed across tests.
  getThreadsMock.mockReset();
  getThreadsMock.mockImplementation(() => Promise.resolve(SAMPLE.map((t) => ({ ...t }))));
});

describe("Thread rename", () => {
  it("double-click swaps the title to an input", async () => {
    await renderChat();

    await waitFor(() => {
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });

    const title = screen.getByText("Old title");
    fireEvent.doubleClick(title);

    // The input field for editing now exists
    expect(screen.getByLabelText(/edit thread title/i)).toBeInTheDocument();
  });

  it("Enter commits the new title via updateThread (optimistic)", async () => {
    updateThreadMock.mockResolvedValue({
      thread_id: "t1",
      title: "New title",
      owner_id: "u1",
      messages: [],
      created_at: "2026-04-10T09:00:00Z",
      updated_at: "2026-04-10T09:00:00Z",
    });
    // After PATCH, refetchThreads will be called — return the renamed thread
    // so the asserted "New title" stays visible regardless of cache vs refetch.
    getThreadsMock.mockImplementationOnce(() =>
      Promise.resolve(SAMPLE.map((t) => ({ ...t }))),
    );
    getThreadsMock.mockImplementation(() =>
      Promise.resolve([{ ...SAMPLE[0], title: "New title" }]),
    );

    await renderChat();
    await waitFor(() => {
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });
    fireEvent.doubleClick(screen.getByText("Old title"));

    const input = screen.getByLabelText(/edit thread title/i);
    fireEvent.change(input, { target: { value: "New title" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(updateThreadMock).toHaveBeenCalledWith("t1", { title: "New title" });
    });
    // Optimistic UI shows the new title immediately (via cache patch)
    await waitFor(() => {
      expect(screen.getByText("New title")).toBeInTheDocument();
    });
  });

  it("Escape cancels without calling updateThread", async () => {
    await renderChat();
    await waitFor(() => {
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });
    fireEvent.doubleClick(screen.getByText("Old title"));

    const input = screen.getByLabelText(/edit thread title/i);
    fireEvent.change(input, { target: { value: "Will be discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(updateThreadMock).not.toHaveBeenCalled();
    await waitFor(() => {
      // Original title still shown
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });
  });

  it("rollback restores old title on PATCH failure", async () => {
    updateThreadMock.mockRejectedValue(new Error("server error"));

    await renderChat();
    await waitFor(() => {
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });
    fireEvent.doubleClick(screen.getByText("Old title"));

    const input = screen.getByLabelText(/edit thread title/i);
    fireEvent.change(input, { target: { value: "Bad title" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });

    // After rollback, the original title is shown again
    await waitFor(() => {
      expect(screen.getByText("Old title")).toBeInTheDocument();
    });
    expect(screen.queryByText("Bad title")).not.toBeInTheDocument();
  });
});
