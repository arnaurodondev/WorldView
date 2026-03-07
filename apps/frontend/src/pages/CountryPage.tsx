import { useParams } from "react-router-dom";

export function CountryPage() {
  const { code } = useParams<{ code: string }>();

  return (
    <div>
      <h2>Country: {code?.toUpperCase()}</h2>
      <p style={{ color: "var(--text-secondary)" }}>
        Country-specific news, economic indicators, and market signals.
      </p>
    </div>
  );
}
