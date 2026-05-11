# Next.js 15 — Developer Guide for Worldview Frontend

> **Who this is for**: Anyone new to Next.js 15 App Router who needs to understand the patterns
> used in this project before touching the code.
>
> **What this covers**: Core App Router concepts, this project's specific conventions,
> annotated code examples, and the most common traps to avoid.
>
> **Companion docs**:
> - `docs/ui/DESIGN_SYSTEM.md` — colors, typography, component catalogue
> - `docs/ui/frontend-migration.md` — architecture decisions (ADRs), full component spec
> - `docs/apps/frontend.md` — quick reference: routes, stack, state management table

---

## Table of Contents

1. [How Next.js App Router differs from React Router](#1-how-nextjs-app-router-differs-from-react-router)
2. [Server vs Client Components — the most important concept](#2-server-vs-client-components)
3. [File conventions](#3-file-conventions)
4. [Data fetching with TanStack Query](#4-data-fetching-with-tanstack-query)
5. [State management — what goes where](#5-state-management)
6. [Auth pattern in this project](#6-auth-pattern)
7. [Real-time: WebSocket and SSE](#7-real-time-websocket-and-sse)
8. [Styling: Tailwind + shadcn/ui](#8-styling-tailwind--shadcnui)
9. [Component structure rules](#9-component-structure-rules)
10. [Common pitfalls](#10-common-pitfalls)
11. [Testing patterns](#11-testing-patterns)

---

## 1. How Next.js App Router differs from React Router

### The old way (current Vite app)

In the current React + Vite app (`apps/frontend/src/App.tsx`), routing works like this:

```tsx
// App.tsx — React Router approach
// All routes are defined in one place.
// The browser downloads ALL component code upfront.
// react-router-dom matches the URL and renders the right component.

import { BrowserRouter, Routes, Route } from "react-router-dom";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/companies/:id" element={<CompanyDetailPage />} />
        {/* etc. */}
      </Routes>
    </BrowserRouter>
  );
}
```

### The new way (Next.js App Router)

Next.js uses the **file system as the router**. There is no `<Routes>` or `<Route>` anywhere.
Instead, the folder structure under `app/` IS the route definition.

```
app/
├── page.tsx                        → renders at URL "/"
├── layout.tsx                      → wraps ALL pages (navbar, providers)
├── login/
│   └── page.tsx                    → renders at URL "/login"
└── (protected)/                    → route GROUP — does NOT add to URL
    ├── layout.tsx                  → wraps only protected pages
    ├── dashboard/
    │   └── page.tsx                → renders at URL "/dashboard"
    └── companies/
        ├── page.tsx                → renders at URL "/companies"
        └── [id]/
            └── page.tsx            → renders at URL "/companies/AAPL" (id = "AAPL")
```

**Key rules:**
- `page.tsx` = the component shown at that URL
- `layout.tsx` = wrapper that PERSISTS across navigations (sidebar stays rendered)
- `[id]` in a folder name = dynamic segment (like `:id` in React Router)
- `(name)` in a folder name = route group — groups pages together but adds NOTHING to the URL

---

## 2. Server vs Client Components

This is the **most important concept** in Next.js 15. Understanding it prevents 90% of bugs.

### Server Components (the default)

By default, every component in the `app/` directory is a **Server Component**.
Server Components run only on the server. They NEVER run in the browser.

```tsx
// app/(protected)/companies/page.tsx
// This is a Server Component — no "use client" directive at the top.
// It runs on the server ONLY.
// It can do things browsers cannot: read the filesystem, call databases directly, etc.
// But it CANNOT use: useState, useEffect, useRef, event handlers, browser APIs.

// For Worldview, most page.tsx files are actually "use client" because
// they use TanStack Query hooks. But the layout files can be Server Components.

export default function CompaniesPage() {
  // ✅ Valid in Server Component: static rendering
  return <h1>Companies</h1>;

  // ❌ INVALID in Server Component — would throw at build time:
  // const [count, setCount] = useState(0);
  // useEffect(() => { ... }, []);
}
```

### Client Components

Add `"use client"` at the very top of a file to make it a Client Component.
Client Components behave exactly like traditional React components.
They run in the browser and can use all React hooks.

```tsx
// src/components/alerts/FlashOverlay.tsx
"use client"  // ← This ONE LINE makes this entire file a Client Component

// Now we can use all React features:
import { useEffect, useState } from "react";

export function FlashOverlay({ alert, onDismiss }) {
  // ✅ Valid: Client Component can use hooks
  useEffect(() => {
    const timer = setTimeout(onDismiss, 12_000);
    return () => clearTimeout(timer);       // cleanup: very important! always return cleanup
  }, [alert.alert_id, onDismiss]);          // deps array: only re-run when these change

  // ✅ Valid: Client Component can attach browser event listeners
  useEffect(() => {
    const handler = (e) => { if (e.key === "Escape") onDismiss(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler); // cleanup
  }, [onDismiss]);

  return <div>...</div>;
}
```

### The boundary rule (critical)

**A Server Component CAN render a Client Component as a child.**
**A Client Component CANNOT import a Server Component as a child.**

```tsx
// app/layout.tsx — Server layout
// This is the root layout — it wraps the entire app.
// It is a Server Component, but it imports Client Components as children.
// This is fine.

import { AuthProvider } from "@/src/contexts/AuthContext";      // "use client"
import { QueryClientProvider } from "@/src/providers/query";   // "use client"

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      {/*
        Set className="dark" PERMANENTLY on the html element.
        shadcn/ui reads this class to apply the dark theme CSS variables.
        We never toggle this — Worldview is always dark (ADR-F-04).
      */}
      <body>
        {/*
          AuthProvider wraps everything because pages need auth state.
          QueryClientProvider wraps everything because pages use TanStack Query.
          These are both "use client" components, but they can be children of
          this Server Component layout — that is perfectly valid.
        */}
        <AuthProvider>
          <QueryClientProvider>
            {children}
          </QueryClientProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
```

### Decision table for this project

| File | Server or Client? | Why |
|------|-----------------|----|
| `app/layout.tsx` | Server | Static shell; providers are children |
| `app/page.tsx` (landing) | Server or Client | Static marketing page |
| `app/(protected)/layout.tsx` | **Client** | Needs `useAuth()` to redirect to /login |
| Any page with TanStack Query | **Client** | `useQuery` is a hook = browser only |
| `AppSidebar.tsx` | Server | Just nav links, no interactivity |
| `TopBar.tsx` | **Client** | Reads `useAuth()` for username |
| `OHLCVChart.tsx` | **Client** | `lightweight-charts` uses DOM/Canvas |
| `AlertCard.tsx` | Server | Pure display — no hooks |
| `useAlertStream.ts` | **Client** | WebSocket uses browser API |
| Any hook file (`use*.ts`) | **Client** | Hooks run in browser |

**Rule of thumb**: If in doubt, add `"use client"`. The penalty is small. The crash from
forgetting it in a Server Component is very visible.

---

## 3. File Conventions

### `page.tsx` — the route component

```
app/(protected)/companies/[id]/page.tsx
```

```tsx
"use client"
// Every page.tsx that fetches data will be "use client" in this project
// because we use TanStack Query hooks.

// Next.js passes params from the URL as props to page components.
// For a dynamic route [id], params will be { id: "AAPL" }.
export default function CompanyDetailPage({
  params,
}: {
  params: { id: string };  // matches the [id] folder name
}) {
  const { id } = params;
  // ...use id to fetch data
}
```

### `layout.tsx` — persistent wrapper

```tsx
// app/(protected)/layout.tsx
// This layout wraps ALL pages inside (protected)/.
// It stays MOUNTED across navigations within the group —
// meaning the sidebar doesn't re-render when you go from /dashboard to /companies.
// This is the main performance advantage over React Router.

"use client"  // needs useAuth which is a hook

import { useAuth } from "@/src/hooks/useAuth";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppSidebar } from "@/src/components/layout/AppSidebar";

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // If auth check is done and user is not authenticated, redirect to login.
    // useEffect is needed because router.push is a side effect.
    if (!isLoading && !isAuthenticated) {
      router.push("/login");
    }
  }, [isAuthenticated, isLoading, router]);

  // Show spinner while checking auth state on mount (silent refresh in progress)
  if (isLoading) return <div className="flex h-screen items-center justify-center">
    <span className="text-muted-foreground text-sm">Loading...</span>
  </div>;

  // Don't flash the protected content before the redirect fires
  if (!isAuthenticated) return null;

  return (
    <div className="flex h-screen overflow-hidden">
      <AppSidebar />
      {/* main takes remaining width; overflow-auto enables page-level scroll */}
      <main className="flex-1 overflow-auto p-6">
        {children}
      </main>
    </div>
  );
}
```

### `loading.tsx` — automatic loading UI (optional)

If you create a `loading.tsx` next to a `page.tsx`, Next.js automatically shows it while the page
is loading. We don't heavily use this pattern — we handle loading states inside components instead
(see §9 Component structure rules).

### `error.tsx` — error boundary (optional)

Similarly, `error.tsx` wraps a route in an error boundary. We use manual error handling
inside components for now.

---

## 4. Data Fetching with TanStack Query

**Rule**: Never use `useState` + `useEffect` to fetch data. Always use TanStack Query.

### Why TanStack Query instead of useEffect?

```tsx
// ❌ THE OLD WAY — do not do this
function BadPanel({ id }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Problems with this approach:
    // 1. Race conditions: two rapid navigations can set stale data
    // 2. No caching: re-fetches every mount, even if you just saw this data
    // 3. No background refresh: stale data shows to users
    // 4. No retry on failure
    // 5. No deduplication: two components asking for same data = two requests
    fetch(`/api/v1/companies/${id}`)
      .then(r => r.json())
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [id]);
}

// ✅ THE RIGHT WAY — TanStack Query handles all of this
function GoodPanel({ id }) {
  const { data, isLoading, error, refetch } = useQuery({
    // queryKey: unique identifier for this query.
    // TanStack Query caches by key. If another component uses the same key,
    // they share the same cached data — no duplicate requests.
    queryKey: ["company", id],

    // queryFn: the async function that fetches the data.
    // Must return a promise. If it throws, TanStack Query handles the error.
    queryFn: () => gateway.getCompanyOverview(id),

    // enabled: if false, the query never fires. Use this for conditional fetching.
    // Here: don't fetch if id is undefined (route param not yet available).
    enabled: !!id,

    // staleTime (optional): how long cached data is considered fresh.
    // During this window, navigating back won't re-fetch.
    // Default: 0 (always re-fetch in background on window focus).
    // staleTime: 60_000,  // 60 seconds — good for rarely-changing data
  });
}
```

### The required three-state pattern

**Every component that fetches data MUST handle all three states.** No exceptions.

```tsx
"use client"

import { useQuery } from "@tanstack/react-query";
import { gateway } from "@/src/lib/gateway-client";
import { Skeleton } from "@/src/components/ui/skeleton";  // shadcn/ui

interface CompanyDetailPanelProps {
  id: string;
}

export function CompanyDetailPanel({ id }: CompanyDetailPanelProps) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["company", id],
    queryFn: () => gateway.getCompanyOverview(id),
    enabled: !!id,
  });

  // ── 1. Loading state ──────────────────────────────────────────────────────
  // Show skeleton placeholders while data is fetching.
  // NEVER show an empty panel — it looks broken.
  if (isLoading) {
    return (
      <div className="space-y-3 p-4">
        {/* Skeleton: animated placeholder with the same shape as the real content */}
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    );
  }

  // ── 2. Error state ────────────────────────────────────────────────────────
  // Show an error message with a retry button.
  // Never silently fail — the user needs to know something went wrong.
  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 p-4">
        <p className="text-sm text-destructive">Failed to load company data.</p>
        <button
          onClick={() => refetch()}     // retry the query
          className="mt-2 text-xs text-muted-foreground underline"
        >
          Try again
        </button>
      </div>
    );
  }

  // ── 3. Empty state ────────────────────────────────────────────────────────
  // Data loaded successfully but nothing to show.
  // This can happen when a valid API call returns an empty collection.
  if (!data) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No data available.
      </div>
    );
  }

  // ── 4. Happy path ─────────────────────────────────────────────────────────
  // Render the actual content. At this point, `data` is fully typed and defined.
  return (
    <div className="p-4">
      <h2 className="text-lg font-semibold">{data.company_id}</h2>
      {/* ... */}
    </div>
  );
}
```

### Mutation (POST / DELETE)

For write operations (creating, updating, deleting), use `useMutation`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";

function AcknowledgeButton({ alertId }: { alertId: string }) {
  const queryClient = useQueryClient();

  const { mutate, isPending } = useMutation({
    // mutationFn: the async operation. Receives the variables passed to mutate().
    mutationFn: (id: string) => gateway.acknowledgeAlert(id),

    // onSuccess: called after the server confirms the mutation.
    // Here we invalidate the pending alerts query so the list refreshes.
    onSuccess: () => {
      // invalidateQueries: tells TanStack Query that cached data for this key is stale.
      // It will re-fetch the data the next time it's needed.
      queryClient.invalidateQueries({ queryKey: ["alerts", "pending"] });
    },
  });

  return (
    <button
      onClick={() => mutate(alertId)}
      disabled={isPending}  // prevent double-clicks while the request is in flight
      className="..."
    >
      {isPending ? "Acknowledging..." : "Acknowledge"}
    </button>
  );
}
```

---

## 5. State Management

Different types of state live in different places. Mixing these up causes bugs.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STATE TYPE         │  WHERE IT LIVES           │  EXAMPLE                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Server data        │  TanStack Query cache     │  Company overview, news   │
│  (fetched from API) │                           │  articles, screener results│
├─────────────────────────────────────────────────────────────────────────────┤
│  Auth state         │  AuthContext (React ctx)  │  accessToken, user info,  │
│                     │                           │  isAuthenticated          │
├─────────────────────────────────────────────────────────────────────────────┤
│  Real-time stream   │  AlertStreamContext       │  criticalQueue,           │
│                     │                           │  recentAlerts             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Workspace layout   │  Zustand + localStorage   │  Panel positions, sizes   │
│                     │                           │  Active ticker in panels  │
├─────────────────────────────────────────────────────────────────────────────┤
│  Simple local UI    │  useState / useReducer    │  Modal open, filter value,│
│                     │  (component-local)        │  tab index                │
├─────────────────────────────────────────────────────────────────────────────┤
│  User preferences   │  localStorage             │  Fundamentals metric set  │
│  (persisted)        │                           │  (FundamentalsBar)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### When to use React Context

Use Context when multiple components need the same state, but the data doesn't come from an API.
If it comes from an API, use TanStack Query instead.

```tsx
// src/contexts/AuthContext.tsx
"use client"

import { createContext, useContext, useState, useEffect } from "react";
import type { ReactNode } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface User {
  user_id: string;
  tenant_id: string;
  email: string;
  sub: string;  // Zitadel subject identifier
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;  // true while silent refresh is in progress on mount
}

interface AuthContextValue extends AuthState {
  login: () => void;
  logout: () => void;
  setAccessToken: (token: string, user: User) => void;
}

// ── Context creation ───────────────────────────────────────────────────────────

// createContext requires a default value. We use a safe empty state.
// The real values come from AuthProvider below.
const AuthContext = createContext<AuthContextValue>({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isLoading: true,  // start as loading — we don't know auth state yet
  login: () => {},
  logout: () => {},
  setAccessToken: () => {},
});

// ── Provider ───────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    isAuthenticated: false,
    isLoading: true,  // start loading — will attempt silent refresh
  });

  // Silent refresh on mount: try to get a new access_token using the
  // httpOnly refresh_token cookie (browser sends it automatically).
  // This is what keeps users logged in across page refreshes.
  useEffect(() => {
    fetch("/api/v1/auth/refresh", { method: "POST" })
      .then((r) => r.ok ? r.json() : null)
      .then((data: { access_token: string; user: User } | null) => {
        if (data) {
          // Silent refresh succeeded — user is logged in
          setState({
            user: data.user,
            accessToken: data.access_token,
            isAuthenticated: true,
            isLoading: false,
          });
        } else {
          // No valid refresh token — user must log in
          setState({ user: null, accessToken: null, isAuthenticated: false, isLoading: false });
        }
      })
      .catch(() => {
        // Network error — assume not authenticated
        setState({ user: null, accessToken: null, isAuthenticated: false, isLoading: false });
      });
  }, []); // [] = run once on mount, never again

  const login = () => {
    // Redirect to S9 auth endpoint which issues a 302 to Zitadel.
    // S9 handles the OIDC flow — the frontend just follows the redirect.
    window.location.href = "/api/v1/auth/login";
  };

  const logout = () => {
    fetch("/api/v1/auth/logout", { method: "POST" })
      .finally(() => {
        // Clear state regardless of server response
        setState({ user: null, accessToken: null, isAuthenticated: false, isLoading: false });
        window.location.href = "/login";
      });
  };

  const setAccessToken = (token: string, user: User) => {
    // Called by CallbackPage after the OIDC code exchange completes
    setState({ user, accessToken: token, isAuthenticated: true, isLoading: false });
  };

  return (
    <AuthContext.Provider value={{ ...state, login, logout, setAccessToken }}>
      {children}
    </AuthContext.Provider>
  );
}

// ── Consumer hook ──────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  // Invariant check: using useAuth outside of AuthProvider is a programming error
  if (value === undefined) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
}
```

---

## 6. Auth Pattern

This project uses Zitadel (external OIDC provider) with S9 as the backend auth handler.
The frontend never touches Zitadel directly — it only talks to S9.

### The full auth flow

```
1. User visits /dashboard (protected route)
   ↓
2. (protected)/layout.tsx checks isAuthenticated
   ↓ not authenticated
3. Redirect to /login
   ↓
4. LoginPage: user clicks "Log in to Worldview"
   ↓
5. Browser navigates to /api/v1/auth/login
   ↓
6. S9 issues 302 redirect to Zitadel with PKCE challenge
   ↓
7. User authenticates on Zitadel
   ↓
8. Zitadel redirects to /callback?code=XXX&state=YYY
   ↓
9. CallbackPage calls GET /api/v1/auth/callback?code=XXX&state=YYY
   ↓
10. S9 exchanges code for tokens, issues httpOnly refresh_token cookie
    + returns access_token + user info in response body
   ↓
11. CallbackPage calls setAccessToken(token, user) → AuthContext updated
   ↓
12. CallbackPage calls router.push("/dashboard")
   ↓
13. ProtectedLayout sees isAuthenticated=true → renders children
```

### Access token storage rule

**CRITICAL**: The access token is stored in React state ONLY — never in localStorage or cookies.

```tsx
// ✅ Correct: token in React state (lives in memory, not persisted)
const [accessToken, setAccessToken] = useState<string | null>(null);

// ❌ Never do this — XSS can steal it
localStorage.setItem("access_token", token);

// ❌ Never do this — readable by JS
document.cookie = `access_token=${token}`;
```

The refresh token is stored as an **httpOnly cookie** by S9 (the server sets it).
httpOnly cookies are invisible to JavaScript — they cannot be stolen by XSS attacks.

### The authClient fetch wrapper

All API calls go through `src/lib/authClient.ts` which automatically:
1. Attaches the Bearer token to every request
2. On 401: silently refreshes the token and retries
3. On second 401: redirects to /login

```tsx
// src/lib/authClient.ts
// This is what gateway-client.ts uses internally.
// You never call authClient directly — always use gateway.someMethod().

// Simplified version of what it does:
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Step 1: try the request with current token
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      // Attach the current access token from AuthContext
      "Authorization": `Bearer ${getAccessTokenFromContext()}`,
      ...init?.headers,
    },
  });

  // Step 2: if 401, try to refresh the token once
  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      // Retry with new token
      return request<T>(path, init);
    }
    // Refresh failed — force login
    router.push("/login");
    throw new Error("Authentication required");
  }

  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }

  return response.json() as Promise<T>;
}
```

---

## 7. Real-Time: WebSocket and SSE

### WebSocket — alert stream

The alert stream uses WebSocket because it needs a persistent bidirectional connection.
The existing `useAlertStream.ts` hook handles this correctly and is being ported to Next.js.

Key patterns to preserve in the port:

```tsx
// src/hooks/useAlertStream.ts
"use client"

import { useState, useEffect, useCallback } from "react";

export function useAlertStream(accessToken: string | null) {
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  const [recentAlerts, setRecentAlerts] = useState<AlertPayload[]>([]);

  useEffect(() => {
    // Guard: don't connect without a token
    if (!accessToken) return;

    let cancelled = false;  // ← tracks if this effect instance was cleaned up
    let retryDelay = 1000;  // ← exponential backoff start: 1 second
    let currentWs: WebSocket | null = null;

    function connect() {
      if (cancelled) return;  // don't reconnect after unmount

      // In Next.js, WebSocket cannot go through the /api proxy rewrite.
      // Use the full URL directly. NEXT_PUBLIC_WS_BASE_URL is set in .env.
      const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8000";
      const ws = new WebSocket(`${wsBase}/v1/alerts/stream?token=${accessToken}`);
      currentWs = ws;

      ws.onopen = () => {
        retryDelay = 1000;  // reset backoff on success
      };

      ws.onmessage = (event) => { /* parse and route to queues */ };

      ws.onclose = () => {
        if (!cancelled) {
          // Wait retryDelay ms then try to reconnect
          setTimeout(connect, retryDelay);
          // Double the delay each time, capped at 30 seconds
          retryDelay = Math.min(retryDelay * 2, 30_000);
        }
      };

      ws.onerror = () => {
        ws.close();  // triggers onclose which handles retry
      };
    }

    connect();

    // Cleanup function: called when component unmounts OR accessToken changes.
    // ALWAYS clean up subscriptions/timers/WebSockets in useEffect — otherwise
    // they keep running in the background causing memory leaks and stale updates.
    return () => {
      cancelled = true;
      currentWs?.close();
    };
  }, [accessToken]);  // re-run if token changes (e.g., after refresh)

  const dequeueCritical = useCallback(
    () => setCriticalQueue((q) => q.slice(1)),
    [],
  );

  return { criticalQueue, recentAlerts, dequeueCritical };
}
```

### SSE — chat streaming

SSE (Server-Sent Events) is a one-way stream from server to browser.
It's perfect for the chat feature where the AI response streams token by token.

```tsx
// src/components/chat/ChatUI.tsx
"use client"

import { useState, useRef, useCallback } from "react";

// State machine for the chat stream:
// idle → sending → streaming → reconciling → settled
// This prevents intermediate states (e.g., can't submit while already streaming)
type StreamState = "idle" | "sending" | "streaming" | "reconciling" | "settled";

export function ChatUI() {
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingText, setStreamingText] = useState("");

  // useRef: stores the AbortController without causing re-renders.
  // When we need to cancel the stream (user clicks Stop or component unmounts),
  // we call abortRef.current?.abort().
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback((text: string) => {
    setStreamState("sending");
    setStreamingText("");

    // Create a new abort controller for this request.
    // This lets us cancel mid-stream if needed.
    const abort = new AbortController();
    abortRef.current = abort;

    // EventSource doesn't support abort signals directly.
    // For cancel support, we use fetch with SSE manually or close the EventSource.
    const eventSource = new EventSource(
      `/api/v1/chat/stream?q=${encodeURIComponent(text)}&token=${getToken()}`
    );

    setStreamState("streaming");

    // Each SSE message is a chunk of the AI response
    eventSource.onmessage = (event) => {
      if (event.data === "[DONE]") {
        // Stream complete: move streaming text to messages array
        setStreamState("reconciling");
        setMessages(prev => [...prev, { role: "assistant", text: streamingText }]);
        setStreamingText("");
        eventSource.close();
        setStreamState("settled");
        return;
      }
      // Append each chunk to the streaming buffer
      setStreamingText(prev => prev + event.data);
    };

    eventSource.onerror = () => {
      eventSource.close();
      setStreamState("idle");
    };
  }, []);

  const cancelStream = () => {
    abortRef.current?.abort();
    setStreamState("idle");
    setStreamingText("");
  };

  return (
    <div>
      {/* Show streaming text as it arrives */}
      {streamState === "streaming" && (
        <div className="text-muted-foreground">
          {streamingText}
          <button onClick={cancelStream}>Stop</button>
        </div>
      )}
      {/* ... message list and input */}
    </div>
  );
}
```

---

## 8. Styling: Tailwind + shadcn/ui

### Tailwind basics

Tailwind is a utility-first CSS framework. Instead of writing CSS classes, you use
pre-defined utility classes directly in JSX.

```tsx
// Old approach (current Vite app — DO NOT use in Next.js migration):
<div style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>text</div>

// New approach (Tailwind):
<div className="text-muted-foreground text-sm">text</div>
```

The key color tokens for this project (maps to CSS variables from `globals.css`):

| Tailwind class | What it renders | Use for |
|----------------|-----------------|---------|
| `bg-background` | `#131722` | Page backgrounds |
| `bg-card` | `#1E2329` | Panel/card backgrounds |
| `bg-muted` | `#2B3139` | Hover states, input backgrounds |
| `text-foreground` | `#D1D4DC` | Primary text |
| `text-muted-foreground` | `#787B86` | Labels, timestamps, secondary text |
| `text-primary` | `#0EA5E9` | Sky accent — links, active states |
| `border-border` | `#2B3139` | Dividers, card borders |
| `text-destructive` | `#EF5350` | Error states, negative values |

```tsx
// Example: a data card
<div className="rounded-lg border border-border bg-card p-4">
  <h3 className="text-sm font-semibold text-foreground">AAPL</h3>
  <p className="mt-1 font-mono text-xs text-muted-foreground">Apple Inc.</p>
  <span className="font-mono text-lg text-positive">+2.34%</span>
</div>
```

**Number rule (ADR-F-15)**: All numeric values (prices, percentages, dates in tables) MUST use
`font-mono` (IBM Plex Mono). This is the single highest-impact rule for professional appearance.

```tsx
// ✅ Correct
<span className="font-mono text-sm">$182.34</span>
<span className="font-mono text-sm tabular-nums">+2.34%</span>

// ❌ Wrong — prices displayed with sans-serif look amateurish
<span className="text-sm">$182.34</span>
```

### shadcn/ui

shadcn/ui is NOT a component library — it's a collection of component recipes that get
copied into your project. You install them with:

```bash
pnpm dlx shadcn@latest add button card tabs badge skeleton
```

After running this, the component code appears in `src/components/ui/` and you own it
completely. You can read and modify it.

```tsx
// Using shadcn/ui components — they are just regular imports
import { Button } from "@/src/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/src/components/ui/card";
import { Badge } from "@/src/components/ui/badge";
import { Skeleton } from "@/src/components/ui/skeleton";

export function ArticleCard({ article }) {
  return (
    // Card: bg-card + border + rounded (all from the CSS variables)
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          {/* Badge: uses variant prop for styling */}
          <Badge variant="secondary">{article.source}</Badge>
          <span className="font-mono text-xs text-muted-foreground">
            {formatRelativeTime(article.published_at)}
          </span>
        </div>
        <CardTitle className="text-sm font-medium leading-snug">
          <a href={article.url} target="_blank" rel="noreferrer"
             className="hover:text-primary transition-colors">
            {article.title}
          </a>
        </CardTitle>
      </CardHeader>
    </Card>
  );
}
```

### cn() — conditional class merging

Use the `cn()` utility for conditional classes. It merges Tailwind classes correctly
(prevents conflicts like two `text-*` classes both applying):

```tsx
import { cn } from "@/src/lib/utils";  // generated by shadcn/ui setup

// Instead of string concatenation:
// ❌ <div className={`text-sm ${isActive ? "text-primary" : "text-muted-foreground"}`}>

// ✅ Use cn():
<div className={cn(
  "text-sm font-medium",
  isActive ? "text-primary" : "text-muted-foreground",
  isDisabled && "opacity-50 cursor-not-allowed",
)}>
```

---

## 9. Component Structure Rules

### The four-state pattern (required for all data components)

Every component that fetches or receives async data MUST render correctly in all four states.
See §4 for the full pattern with code. The rule: never leave a panel blank.

### File structure for a component

```tsx
// src/components/news/ArticleCard.tsx
// ─────────────────────────────────────────────────────────────────────────────
// "use client" or not, depending on whether this component uses hooks.
// ArticleCard is pure display with no hooks → can be a Server Component.
// But if it uses ImpactSparkline (which uses lightweight-charts) it becomes Client.

import type { RankedArticle } from "@/src/lib/gateway-client";  // types only
import { RelevanceBadge } from "./RelevanceBadge";
import { ImpactSparkline } from "./ImpactSparkline";
import { Card, CardContent } from "@/src/components/ui/card";
import { cn } from "@/src/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────────

interface ArticleCardProps {
  article: RankedArticle;
  showEntity?: boolean;  // optional with default below
}

// ── Component ──────────────────────────────────────────────────────────────────

export function ArticleCard({ article, showEntity = true }: ArticleCardProps) {
  // Computed values: derive from props, not from state
  const isLight = article.routing_tier === "LIGHT";  // de-emphasise LIGHT articles
  const hasImpactData =
    article.impact_windows !== null &&
    Object.values(article.impact_windows).filter(Boolean).length >= 2;  // need ≥2 windows

  return (
    <Card
      className={cn(
        "transition-opacity",
        isLight && "opacity-60",  // LIGHT articles are visually de-emphasised (ADR-F-05 OQ-6)
      )}
    >
      <CardContent className="p-3">
        {/* Header row: relevance score + entity ticker + source type */}
        <div className="mb-1 flex items-center gap-2">
          <RelevanceBadge score={article.display_relevance_score} />
          {showEntity && article.primary_entity_symbol && (
            <span className="font-mono text-xs font-medium text-foreground">
              {article.primary_entity_symbol}
            </span>
          )}
          <span
            className={cn(
              "text-xs",
              isLight ? "italic text-muted-foreground" : "text-muted-foreground",
            )}
          >
            {article.source}
          </span>
        </div>

        {/* Article title: external link */}
        <a
          href={article.url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-sm font-medium leading-snug hover:text-primary transition-colors"
        >
          {article.title}
        </a>

        {/* Impact sparkline: only when we have enough data points */}
        {hasImpactData && article.impact_windows && (
          <div className="mt-2">
            <ImpactSparkline windows={article.impact_windows} height={48} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

### Naming conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Component files | PascalCase | `ArticleCard.tsx` |
| Hook files | camelCase starting with `use` | `useAlertStream.ts` |
| Utility/lib files | camelCase | `gateway-client.ts` |
| Page components | default export | `export default function CompaniesPage()` |
| Non-page components | named export | `export function ArticleCard()` |
| Types/interfaces | PascalCase with descriptive name | `interface RankedArticle` |

---

## 10. Common Pitfalls

### Pitfall 1: Forgetting `"use client"` for hooks

```tsx
// ❌ This crashes at build time with:
//    "You're importing a component that needs useState. It only works in a Client Component."
import { useState } from "react";

export function Broken() {  // No "use client" at top of file
  const [count, setCount] = useState(0);  // ← ERROR: hooks not allowed in Server Components
}

// ✅ Add "use client" at the very top
"use client"  // ← must be the FIRST LINE, before even imports
import { useState } from "react";

export function Fixed() {
  const [count, setCount] = useState(0);  // ✅ works
}
```

### Pitfall 2: Hydration mismatch

Hydration is the process where React "attaches" to server-rendered HTML.
A mismatch happens when the server renders different content than the client expects.

```tsx
// ❌ Hydration error: Math.random() gives a different value on server vs client
export function BadComponent() {
  return <div>{Math.random()}</div>;
}

// ❌ Hydration error: new Date() gives different timestamp on server vs client
export function AnotherBadComponent() {
  return <div>{new Date().toLocaleTimeString()}</div>;
}

// ✅ Use suppressHydrationWarning for intentional mismatches (rare)
// ✅ Or move the dynamic content into a "use client" component with useEffect
"use client"
export function GoodComponent() {
  const [time, setTime] = useState<string>("");
  useEffect(() => {
    // This only runs in the browser — no server/client mismatch
    setTime(new Date().toLocaleTimeString());
  }, []);
  return <div>{time}</div>;
}
```

### Pitfall 3: `useRouter` from the wrong package

Next.js 15 App Router has TWO different router packages. Importing from the wrong one
causes confusing errors.

```tsx
// ❌ WRONG for App Router pages
import { useRouter } from "next/router";      // this is the OLD Pages Router

// ✅ CORRECT for App Router pages
import { useRouter } from "next/navigation";  // always use this
import { usePathname } from "next/navigation";
import { useSearchParams } from "next/navigation";
```

### Pitfall 4: Missing useEffect cleanup

Forgetting cleanup causes memory leaks, stale state updates on unmounted components,
and duplicate WebSocket connections.

```tsx
// ❌ Memory leak: timer keeps running after component unmounts
useEffect(() => {
  const interval = setInterval(() => {
    refetch();
  }, 30_000);
  // No return! Timer never gets cleared.
}, []);

// ✅ Always return a cleanup function
useEffect(() => {
  const interval = setInterval(() => {
    refetch();
  }, 30_000);
  return () => clearInterval(interval);  // ← runs on unmount
}, [refetch]);
```

### Pitfall 5: Stale closures in useEffect

```tsx
// ❌ Stale closure: onDismiss might be a stale reference
useEffect(() => {
  const timer = setTimeout(onDismiss, 12_000);
  return () => clearTimeout(timer);
}, []);  // ← Empty deps means onDismiss captured at mount time only

// ✅ Include onDismiss in deps array
useEffect(() => {
  const timer = setTimeout(onDismiss, 12_000);
  return () => clearTimeout(timer);
}, [onDismiss]);  // ← re-run if onDismiss changes (wrap caller's version in useCallback)
```

### Pitfall 6: Environment variable access in wrong context

```tsx
// In Next.js:
// - NEXT_PUBLIC_* variables are inlined at build time and available in both server and client
// - Other variables are only available on the server (not in browser code)

// ✅ Accessible everywhere (client + server)
const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL;

// ❌ Only accessible server-side — will be undefined in "use client" components
const secret = process.env.SOME_API_SECRET;  // undefined in browser!
```

### Pitfall 7: next/image vs regular img

```tsx
// For regular images (icons, static assets), use the Next.js <Image> component
// It handles lazy loading, sizing, and optimization automatically.
import Image from "next/image";

// ✅
<Image src="/logo.png" alt="Worldview" width={120} height={32} />

// For external images not in /public, you must add the domain to next.config.ts
// In this project, we mostly use Lucide icons (SVG via lucide-react) so this is rare.
```

### Pitfall 8: Infinite re-render loops

```tsx
// ❌ Infinite loop: calling setState inside useEffect without deps
//    The effect runs → setState → component re-renders → effect runs again
"use client"
function BadComponent() {
  const [data, setData] = useState(null);
  useEffect(() => {
    setData(computeSomething());  // triggers re-render → effect runs again → infinite loop
  });  // ← missing deps array!

// ✅ Always provide a deps array (even empty [] to run once)
  useEffect(() => {
    setData(computeSomething());
  }, []);  // ← runs only on mount
```

---

## 11. Testing Patterns

### Vitest + React Testing Library (unit tests)

Tests live in `tests/` (or `__tests__/`) next to `src/`. Configuration in `vitest.config.ts`.

```tsx
// tests/RelevanceBadge.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RelevanceBadge } from "@/src/components/news/RelevanceBadge";

describe("RelevanceBadge", () => {
  it("shows score as percentage", () => {
    render(<RelevanceBadge score={0.87} />);
    // getByText: finds element containing this text
    expect(screen.getByText("87%")).toBeInTheDocument();
  });

  it("applies red colour for score ≥ 0.8", () => {
    render(<RelevanceBadge score={0.85} />);
    const badge = screen.getByText("85%").closest("[data-testid]");
    // Check CSS class (the className for high-relevance articles)
    expect(badge).toHaveClass("bg-red-600");
  });

  it("applies grey colour for score < 0.3", () => {
    render(<RelevanceBadge score={0.2} />);
    expect(screen.getByText("20%")).toHaveClass("bg-slate-600");
  });
});
```

### MSW — mocking API calls

MSW (Mock Service Worker) intercepts `fetch` calls in tests.
This is the correct way to test components that call the API — never mock `fetch` directly.

```tsx
// tests/setup.ts (runs before all tests)
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

// Define mock handlers: intercept API calls and return mock responses
export const server = setupServer(
  // Mock the company overview endpoint
  http.get("/api/v1/companies/:id/overview", ({ params }) => {
    return HttpResponse.json({
      company_id: params.id,
      ohlcv: { bars: [] },
      latest_news: { articles: [] },
    });
  }),

  // Mock the auth refresh endpoint (used by AuthProvider on mount)
  http.post("/api/v1/auth/refresh", () => {
    return HttpResponse.json({
      access_token: "fake-token-for-tests",
      user: { user_id: "u1", tenant_id: "t1", email: "test@test.com", sub: "sub1" },
    });
  }),
);

// Start/stop server around tests
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());  // reset overrides after each test
afterAll(() => server.close());
```

### Testing async queries

```tsx
// tests/CompanyDetailPanel.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { CompanyDetailPanel } from "@/src/components/instrument/CompanyDetailPanel";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";

// Helper: wrap component with required providers
function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },  // don't retry on error in tests
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {ui}
    </QueryClientProvider>
  );
}

describe("CompanyDetailPanel", () => {
  it("shows skeleton while loading", () => {
    renderWithProviders(<CompanyDetailPanel id="AAPL" />);
    // Should show skeleton immediately before the mock resolves
    expect(screen.getByTestId("panel-skeleton")).toBeInTheDocument();
  });

  it("shows company data after loading", async () => {
    renderWithProviders(<CompanyDetailPanel id="AAPL" />);
    // waitFor: retries assertion until it passes or times out
    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });
  });
});
```

### Playwright E2E tests

```ts
// e2e/auth.spec.ts
import { test, expect } from "@playwright/test";

test("unauthenticated user is redirected to /login", async ({ page }) => {
  // Try to visit a protected route
  await page.goto("/dashboard");

  // Should land on /login instead
  await expect(page).toHaveURL("/login");
  await expect(page.getByText("Log in to Worldview")).toBeVisible();
});

test("login button redirects to Zitadel", async ({ page }) => {
  await page.goto("/login");

  // Click login → should redirect to Zitadel (external URL)
  // We stop before actually completing the OAuth flow in E2E tests
  const [response] = await Promise.all([
    page.waitForNavigation(),
    page.getByRole("button", { name: "Log in to Worldview" }).click(),
  ]);

  // Should have redirected away from localhost
  expect(page.url()).toContain("zitadel");
});
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WORLDVIEW FRONTEND — QUICK RULES                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  ALWAYS                                                                     │
│  ✅ Add "use client" when using hooks (useState, useEffect, useQuery, etc.) │
│  ✅ Handle loading + error + empty states in every data component           │
│  ✅ Use TanStack Query for all server data (no useState+useEffect fetching) │
│  ✅ Use font-mono (IBM Plex Mono) for ALL numeric values                    │
│  ✅ Return cleanup from useEffect when using timers/WS/listeners            │
│  ✅ Import router from "next/navigation" (not "next/router")                │
│  ✅ Use gateway.someMethod() for API calls (never raw fetch in components)  │
│  ✅ Use cn() for conditional Tailwind classes                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  NEVER                                                                      │
│  ❌ Store access_token in localStorage or a non-httpOnly cookie             │
│  ❌ Call backend services directly — always go through S9 (/api/*)         │
│  ❌ Use useEffect+setState to fetch data (use TanStack Query instead)       │
│  ❌ Use hardcoded hex colors — always use Tailwind semantic classes         │
│  ❌ Add light mode — className="dark" on <html> is permanent (ADR-F-04)    │
│  ❌ Import from "next/router" in App Router pages (use "next/navigation")   │
└─────────────────────────────────────────────────────────────────────────────┘
```
