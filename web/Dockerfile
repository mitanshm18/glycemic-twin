# syntax=docker/dockerfile:1
# Glycemic Twin web app (Next.js standalone server). Build from web/:
#   docker build -t glycemic-twin-web web
# Behind Caddy the browser reaches the API on the same origin (/api/v1 -> FastAPI); the Next.js
# rewrite (TWIN_API_ORIGIN) is only a fallback and, like TWIN_COOKIE_NAME, is fixed at BUILD time.

ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:${NODE_VERSION}-alpine AS build
WORKDIR /web
ARG TWIN_API_ORIGIN=http://api:8000
ARG TWIN_COOKIE_NAME=twin_session
ENV TWIN_API_ORIGIN=$TWIN_API_ORIGIN \
    TWIN_COOKIE_NAME=$TWIN_COOKIE_NAME \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /web/node_modules node_modules
COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-alpine AS runtime
WORKDIR /web
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
# the standalone server, its traced node_modules, and the static assets it serves
COPY --from=build --chown=node:node /web/.next/standalone ./
COPY --from=build --chown=node:node /web/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]
CMD ["node", "server.js"]
