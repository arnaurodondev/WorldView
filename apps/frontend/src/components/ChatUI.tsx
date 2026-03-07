import { useState, useRef, useEffect } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function ChatUI() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || streaming) return;

    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);

    // Simulated SSE stream (replace with real gateway call)
    const assistantMsg: Message = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, assistantMsg]);

    const mockResponse = "This is a mock streaming response from the RAG service.";
    for (let i = 0; i < mockResponse.length; i++) {
      await new Promise((r) => setTimeout(r, 20));
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: mockResponse.slice(0, i + 1),
        };
        return updated;
      });
    }
    setStreaming(false);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "70vh" }}>
      <div style={{ flex: 1, overflowY: "auto", marginBottom: "1rem" }}>
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              padding: "0.75rem",
              marginBottom: "0.5rem",
              background: msg.role === "user" ? "var(--bg-secondary)" : "transparent",
              borderRadius: "0.5rem",
            }}
          >
            <strong>{msg.role === "user" ? "You" : "Assistant"}: </strong>
            {msg.content}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about companies, news, markets..."
          disabled={streaming}
          style={{
            flex: 1,
            padding: "0.75rem",
            background: "var(--bg-secondary)",
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            color: "var(--text-primary)",
          }}
        />
        <button
          type="submit"
          disabled={streaming}
          style={{
            padding: "0.75rem 1.5rem",
            background: "var(--accent)",
            border: "none",
            borderRadius: "0.5rem",
            color: "white",
            cursor: "pointer",
          }}
        >
          Send
        </button>
      </form>
    </div>
  );
}
