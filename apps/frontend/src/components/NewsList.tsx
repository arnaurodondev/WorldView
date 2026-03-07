import type { Article } from "../lib/gateway-client";

interface NewsListProps {
  articles: Article[];
}

export function NewsList({ articles }: NewsListProps) {
  if (articles.length === 0) {
    return <p style={{ color: "var(--text-secondary)" }}>No articles available.</p>;
  }

  return (
    <ul style={{ listStyle: "none" }}>
      {articles.map((article) => (
        <li
          key={article.id}
          style={{
            padding: "0.75rem 0",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <a href={article.url} target="_blank" rel="noopener noreferrer">
            {article.title}
          </a>
          <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
            {article.source} · {new Date(article.published_at).toLocaleDateString()}
          </div>
        </li>
      ))}
    </ul>
  );
}
