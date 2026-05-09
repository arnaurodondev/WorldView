/**
 * app/(app)/chat/layout.tsx — route-segment metadata wrapper.
 *
 * WHY THIS EXISTS (HF-10 demo-blocker fix): the chat page is a client
 * component (SSE stream, message-input state) and cannot export Next.js
 * `metadata` directly. App Router resolves metadata from the deepest layout,
 * so this server-component layout supplies the per-route <title> without
 * forcing the page to become a server component.
 *
 * SCOPE: pure passthrough — returns {children}. The (app) layout above
 * still wraps the page in TopBar / sidebar / WorkspaceContext.
 */
import type { ReactNode } from "react";

export const metadata = { title: "Chat | Worldview" };

export default function ChatLayout({ children }: { children: ReactNode }) {
  return children;
}
