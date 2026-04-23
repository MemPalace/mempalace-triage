# syntax=docker/dockerfile:1.7

# ─── Stage 1: build the Angular dashboard ─────────────────────────────────────
# Angular CLI requires Node ≥ 22.12; the Bun 1.2.5 image bundles 22.6, so we
# use a dedicated Node stage for the dashboard build. npm here (over bun) keeps
# us aligned with the committed dashboard/package-lock.json.
FROM node:22-alpine AS dashboard-build
WORKDIR /build
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# ─── Stage 2: install server runtime deps ─────────────────────────────────────
FROM oven/bun:1.2.5 AS server-deps
WORKDIR /build
COPY server/package.json server/bun.lock ./
RUN bun install --frozen-lockfile --production

# ─── Stage 3: runtime image ───────────────────────────────────────────────────
FROM oven/bun:1.2.5-slim AS runtime

ARG TARGETARCH
ARG GH_VERSION=2.63.2

# gh CLI is required by the triage poller (fetches issues/PRs/diffs).
# Pull the matching static tarball for the target architecture — no apt repo.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && GH_ARCH="${TARGETARCH:-amd64}" \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${GH_ARCH}.tar.gz" \
    | tar -xz -C /tmp \
 && mv /tmp/gh_*/bin/gh /usr/local/bin/gh \
 && rm -rf /tmp/gh_* \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Server code + production node_modules
COPY server/ /app/server/
COPY --from=server-deps /build/node_modules /app/server/node_modules

# Maintainer allowlist (re-seeded into the DB on every boot)
COPY config/ /app/config/

# Built dashboard served at /
COPY --from=dashboard-build /build/dist/dashboard/browser /app/dashboard-dist

ENV NODE_ENV=production \
    PORT=7800 \
    POLLER_ENABLED=true \
    DASHBOARD_DIST=/app/dashboard-dist \
    DATABASE_URL=/data/triage.db \
    MAINTAINERS_CONFIG=/app/config/maintainers.toml

EXPOSE 7800

WORKDIR /app/server
CMD ["bun", "src/index.ts"]
