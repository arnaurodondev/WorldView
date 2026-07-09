# syntax=docker/dockerfile:1
# Extends timescale/timescaledb with pgvector (already included) + Apache AGE
# for the knowledge-graph service.
#
# Notes:
#   - timescaledb:2.17.2-pg16 is Alpine-based (musl libc; use apk, not apt-get)
#   - PG16 was built --with-llvm using llvm19; PGXS needs llvm19-dev at build time
#   - Alpine ships up to clang17 → override via make variable for PGXS
#   - AGE tags use the format PG<ver>/<version>-rc0 (e.g. PG16/v1.5.0-rc0)
#     git clone --branch can't handle slash-containing tag names directly;
#     we use git fetch + checkout FETCH_HEAD instead.
#
# Build time: ~5-10 min on first `docker compose ... up --build` (cached after).
#
# Pin to a specific timescaledb release to avoid upstream Alpine package churn
# breaking the AGE build (clang/llvm version drift).
FROM timescale/timescaledb:2.17.2-pg16

USER root

# Latest stable AGE release for PG16
ARG AGE_TAG=PG16/v1.5.0-rc0

# Install AGE graph extension. The build needs clang + llvm-dev to match the
# PostgreSQL server's JIT configuration. We try clang17 first (Alpine 3.20/3.21),
# then fall back to plain clang if the versioned package is unavailable.
RUN apk add --no-cache --virtual .build-deps \
        build-base \
        git \
        perl \
        readline-dev \
        zlib-dev \
        flex \
        bison \
    && (apk add --no-cache clang17 llvm19-dev 2>/dev/null \
        || apk add --no-cache clang llvm-dev) \
    && CLANG_BIN=$(command -v clang-17 || command -v clang) \
    && mkdir /tmp/age && cd /tmp/age \
    && git init \
    && git remote add origin https://github.com/apache/age.git \
    && git fetch --depth 1 origin "refs/tags/${AGE_TAG}" \
    && git checkout FETCH_HEAD \
    && make CLANG="$CLANG_BIN" \
    && make install \
    && rm -rf /tmp/age \
    && apk del .build-deps

# Restore non-root user after extension build (F-009)
USER postgres

# Built + pushed to ghcr.io/arnaurodondev/worldview-postgres by .github/workflows/deploy.yml.
