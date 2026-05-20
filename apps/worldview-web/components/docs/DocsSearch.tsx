/**
 * components/docs/DocsSearch.tsx — cmd-K fuzzy search (T-B-2-07)
 *
 * WHY THIS EXISTS: Docs sites with >20 pages are unusable without keyboard
 * search. cmd/ctrl-K is the universal pattern (Stripe, Vercel, Linear,
 * Tailwind, shadcn). Powered by Fuse.js for client-side fuzzy matching
 * over a build-time-precomputed search index.
 *
 * WHY CLIENT COMPONENT: cmd-K binding + dialog state + Fuse search are
 * all client concerns. The index itself is built at server time and
 * passed in as a prop (so it's part of the static page payload — no
 * runtime fetch).
 */

"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import Fuse from "fuse.js";
import { Search, ChevronRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { SearchEntry } from "@/lib/docs";

interface DocsSearchProps {
  index: SearchEntry[];
}

export function DocsSearch({ index }: DocsSearchProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Memoise the Fuse instance — building the index is O(n) and we'd burn
  // CPU rebuilding on every keystroke without this. Threshold 0.35 is
  // moderately fuzzy: typos are forgiven but unrelated keywords don't
  // pollute the result list.
  const fuse = useMemo(
    () =>
      new Fuse(index, {
        keys: [
          { name: "title", weight: 3 },
          { name: "description", weight: 2 },
          { name: "section", weight: 1 },
          { name: "body", weight: 1 },
        ],
        threshold: 0.35,
        ignoreLocation: true,
        includeScore: true,
      }),
    [index],
  );

  // Top 8 matches keep the dropdown skim-able; more results = decision
  // paralysis. Empty query → empty results (no "show all" mode — the
  // sidebar already shows everything).
  const results = useMemo(() => {
    if (!query.trim()) return [];
    return fuse.search(query.trim()).slice(0, 8).map((r) => r.item);
  }, [fuse, query]);

  // Global ⌘K / ctrl-K binding. We register on `document` so the dialog
  // opens regardless of focus. The check `e.metaKey || e.ctrlKey`
  // covers both macOS and Windows/Linux.
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  // Reset query + active row when dialog closes — prevents stale state
  // showing up next time the user opens search.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setActive(0);
    } else {
      // Auto-focus the input on open so the user can type immediately.
      // requestAnimationFrame wait until radix has actually mounted the
      // dialog to the DOM, otherwise the focus call is dropped.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Reset active row when results change so highlighted row doesn't
  // point to an out-of-bounds index after typing more characters.
  useEffect(() => {
    setActive(0);
  }, [query]);

  function navigate(entry: SearchEntry) {
    setOpen(false);
    router.push(entry.hash ? `${entry.url}#${entry.hash}` : entry.url);
  }

  return (
    <>
      {/* Persistent trigger button rendered in the docs header. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-[2px] border border-border/60 bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
      >
        <Search className="h-3.5 w-3.5" aria-hidden="true" />
        Search docs
        <kbd className="ml-2 hidden rounded-[2px] border border-border/40 bg-muted/40 px-1 py-0.5 font-mono text-[10px] sm:inline">
          ⌘K
        </kbd>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        {/* QA iter-1 (a11y responsive m-3): mx-4 + w-[calc(100vw-2rem)]
            keeps the dialog within the viewport on 480px screens. */}
        <DialogContent className="mx-4 w-[calc(100vw-2rem)] max-w-xl gap-0 p-0">
          <DialogTitle className="sr-only">Search documentation</DialogTitle>
          <div className="flex items-center gap-2 border-b border-border/40 px-4 py-3">
            <Search
              className="h-4 w-4 text-muted-foreground"
              aria-hidden="true"
            />
            {/* QA iter-1 (a11y M-A3): WAI-ARIA combobox pattern — input is
                role=combobox with aria-controls + aria-expanded +
                aria-activedescendant pointing to the highlighted option. */}
            <input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-controls="docs-search-listbox"
              aria-expanded={results.length > 0}
              aria-autocomplete="list"
              aria-activedescendant={
                results[active] ? `docs-search-option-${active}` : undefined
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((a) => Math.min(a + 1, Math.max(results.length - 1, 0)));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((a) => Math.max(a - 1, 0));
                } else if (e.key === "Enter" && results[active]) {
                  e.preventDefault();
                  navigate(results[active]);
                }
              }}
              placeholder="Search the docs…"
              aria-label="Search documentation"
              className="flex-1 bg-transparent text-[14px] text-foreground outline-none placeholder:text-muted-foreground/60"
            />
          </div>

          {results.length > 0 ? (
            <ul
              id="docs-search-listbox"
              role="listbox"
              className="max-h-80 overflow-y-auto py-2"
            >
              {results.map((r, i) => (
                <li
                  key={`${r.url}#${r.hash ?? ""}-${i}`}
                  id={`docs-search-option-${i}`}
                  role="option"
                  aria-selected={i === active}
                >
                  <button
                    type="button"
                    onClick={() => navigate(r)}
                    onMouseEnter={() => setActive(i)}
                    // tabIndex=-1 because focus stays on the input
                    // (combobox pattern); button is reachable via mouse +
                    // aria-activedescendant for AT.
                    tabIndex={-1}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-[14px] transition-colors",
                      i === active ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/40",
                    )}
                  >
                    <span className="flex-1 truncate">
                      <span className="font-medium text-foreground">{r.title}</span>
                      {r.description ? (
                        <span className="block truncate text-xs text-muted-foreground/80">
                          {r.description}
                        </span>
                      ) : null}
                    </span>
                    {/* QA iter-1 (design m-D10): bumped to /80 from /60 so
                        the section label is actually readable next to the
                        title row. */}
                    <span className="hidden font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 sm:inline">
                      {r.section}
                    </span>
                    <ChevronRight
                      className="h-3.5 w-3.5 text-muted-foreground/50"
                      aria-hidden="true"
                    />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-4 py-6 text-center text-xs text-muted-foreground">
              {query
                ? <>No matching pages. Try keywords like <em className="text-foreground">quotes</em>, <em className="text-foreground">screener</em>, or <em className="text-foreground">brokerage</em>.</>
                : "Type to search the documentation…"}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
