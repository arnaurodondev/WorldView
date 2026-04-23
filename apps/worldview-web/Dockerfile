# ── worldview-web — Multi-stage Docker build (Next.js 15 standalone) ──────────
#
# Produces a minimal Node.js image (~120 MB) with the Next.js standalone server.
# The standalone output bundles only the modules the app actually imports, so
# there is no need to copy node_modules into the final image.
#
# Build context: repo root (../../) — required because pnpm-lock.yaml and
# pnpm-workspace.yaml live at the workspace root.
# Dockerfile path: apps/worldview-web/Dockerfile
#
# Stages:
#   1. deps     — install workspace dependencies via pnpm
#   2. builder  — run `next build` to produce .next/standalone
#   3. runner   — copy standalone output into a clean Node.js image
#
# Usage (standalone, from repo root):
#   docker build -t worldview-web -f apps/worldview-web/Dockerfile .
#   docker run -p 3001:3001 -e API_GATEWAY_URL=http://host.docker.internal:8000 worldview-web

# ── Stage 1: Install dependencies ─────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /workspace
RUN corepack enable && corepack prepare pnpm@10 --activate
# Copy workspace config + lock file + app package.json for dependency resolution.
# Root package.json must also be copied — it contains `pnpm.overrides` (vite, @eslint/plugin-kit)
# that are recorded in pnpm-lock.yaml. Without it, pnpm raises ERR_PNPM_LOCKFILE_CONFIG_MISMATCH.
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/worldview-web/package.json ./apps/worldview-web/
RUN pnpm install --frozen-lockfile --filter worldview-web

# ── Stage 2: Build the Next.js app ───────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /workspace
RUN corepack enable && corepack prepare pnpm@10 --activate
COPY --from=deps /workspace/node_modules ./node_modules
COPY --from=deps /workspace/apps/worldview-web/node_modules ./apps/worldview-web/node_modules
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/worldview-web ./apps/worldview-web
ENV NEXT_TELEMETRY_DISABLED=1
# Set API_GATEWAY_URL at build time so next.config.ts rewrites() bakes the
# correct Docker-internal hostname into the standalone server.js config.
# next.config.ts rewrites() runs at build time, NOT runtime — the result is
# serialized into the standalone output. Without this ARG, the fallback
# http://localhost:8000 is baked in, which is unreachable inside Docker.
ARG API_GATEWAY_URL=http://api-gateway:8000
ENV API_GATEWAY_URL=${API_GATEWAY_URL}
RUN cd apps/worldview-web && pnpm build

# ── Stage 3: Production runner ───────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone server — pnpm workspace nests output under apps/worldview-web/
COPY --from=builder /workspace/apps/worldview-web/.next/standalone ./
COPY --from=builder /workspace/apps/worldview-web/.next/static ./apps/worldview-web/.next/static
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/worldview-web/public ./apps/worldview-web/public

USER nextjs
EXPOSE 3001
ENV PORT=3001
ENV HOSTNAME="0.0.0.0"

# server.js is nested under the workspace path in standalone output
CMD ["node", "apps/worldview-web/server.js"]
