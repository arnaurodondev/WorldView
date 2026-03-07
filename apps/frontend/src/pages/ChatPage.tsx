import { ChatUI } from "../components/ChatUI";

export function ChatPage() {
  return (
    <div>
      <h2>Intelligence Chat</h2>
      <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Ask questions about companies, markets, and news.
      </p>
      <ChatUI />
    </div>
  );
}
