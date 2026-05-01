/**
 * vitest.server-only-stub.ts — empty replacement for the `server-only`
 * package during Vitest runs.
 *
 * The real `server-only` package only exports a build-time error in
 * client bundles (Next.js webpack flagging). Outside Next.js — like in
 * Vitest — the import resolves to nothing useful and triggers a
 * "Module load failed" error. Aliased to this empty file via
 * vitest.config.ts so server-only-marked modules can be imported by
 * tests.
 */
export {};
