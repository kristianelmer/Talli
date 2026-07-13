# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:24-trixie-slim@sha256:366fdef91728b1b7fa18c84fba63b6e79ed77b7e10cc206878e9705da4d7b169

FROM ${NODE_IMAGE} AS web-dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM web-dependencies AS web-builder
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

FROM ${NODE_IMAGE} AS python-dependencies
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /uvx /bin/
RUN apt-get update \
  && apt-get install --yes --no-install-recommends python3 python3-venv \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM ${NODE_IMAGE} AS runtime
RUN apt-get update \
  && apt-get install --yes --no-install-recommends ca-certificates python3 \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV HOSTNAME=0.0.0.0 \
  NEXT_TELEMETRY_DISABLED=1 \
  NODE_ENV=production \
  PORT=3000 \
  PYTHONDONTWRITEBYTECODE=1 \
  TALLI_PYTHON_BIN=/app/.venv/bin/python \
  TALLI_PYTHON_MAX_OUTPUT_BYTES=20000000 \
  TALLI_PYTHON_TIMEOUT_MS=30000

COPY --from=web-builder --chown=node:node /app/.next/standalone ./
COPY --from=web-builder --chown=node:node /app/.next/static ./.next/static
COPY --from=python-dependencies --chown=node:node /app/.venv ./.venv

USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/api/health').then((response) => { if (!response.ok) process.exit(1); }).catch(() => process.exit(1));"]
CMD ["node", "server.js"]
