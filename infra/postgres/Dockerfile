# syntax=docker/dockerfile:1
# Extends timescale/timescaledb:latest-pg16 with Apache AGE for the
# knowledge-graph service (graph traversal on market entities).
#
# Build time: ~3-5 min on first `docker compose --profile infra up --build`.
# The built image is cached; subsequent starts are instant.
FROM timescale/timescaledb:latest-pg16

USER root

ARG AGE_VERSION=1.5.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        postgresql-server-dev-16 \
        libreadline-dev \
        zlib1g-dev \
        flex \
        bison \
    && git clone --depth 1 --branch "v${AGE_VERSION}" \
        https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age \
    && make \
    && make install \
    && rm -rf /tmp/age \
    && apt-get purge -y --auto-remove \
        build-essential git postgresql-server-dev-16 \
        libreadline-dev zlib1g-dev flex bison \
    && rm -rf /var/lib/apt/lists/*
