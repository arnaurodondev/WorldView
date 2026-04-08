import { Link, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard" },
  { path: "/companies", label: "Companies" },
  { path: "/screener", label: "Screener" },
  { path: "/portfolio", label: "Portfolio" },
  { path: "/news", label: "News" },
  { path: "/map", label: "Map" },
  { path: "/chat", label: "Chat" },
];

export function Layout() {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <nav
        style={{
          width: 220,
          background: "var(--bg-secondary)",
          padding: "1rem",
          borderRight: "1px solid var(--border)",
        }}
      >
        <h1 style={{ fontSize: "1.25rem", marginBottom: "1.5rem" }}>
          Worldview
        </h1>
        <ul style={{ listStyle: "none" }}>
          {NAV_ITEMS.map((item) => (
            <li key={item.path} style={{ marginBottom: "0.5rem" }}>
              <Link to={item.path}>{item.label}</Link>
            </li>
          ))}
        </ul>
      </nav>
      <main style={{ flex: 1, padding: "1.5rem" }}>
        <Outlet />
      </main>
    </div>
  );
}
