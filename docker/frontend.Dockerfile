# syntax=docker/dockerfile:1

# ---- deps -----------------------------------------------------------------
FROM node:20-alpine AS deps

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# ---- dev --------------------------------------------------------------
# Used by docker-compose.yml/override for local development: source is bind
# mounted over /app/src, Vite's dev server serves with HMR.
FROM node:20-alpine AS dev

# node:20-alpine already ships a non-root "node" user at uid/gid 1000 —
# reuse it instead of creating a second one (which collides on that gid).
WORKDIR /app

COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node frontend/ .

USER node

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- builder ----------------------------------------------------------
# Scaffolded for a future static/prod deploy; not wired into compose in
# module 1 (dev target above is what `docker compose up` uses).
FROM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .
RUN npm run build

# ---- prod -------------------------------------------------------------
FROM nginx:1.27-alpine AS prod

RUN addgroup --gid 1000 appuser \
    && adduser --uid 1000 --ingroup appuser --shell /sbin/nologin --disabled-password appuser \
    && chown -R appuser:appuser /var/cache/nginx /var/log/nginx /etc/nginx \
    && touch /run/nginx.pid \
    && chown appuser:appuser /run/nginx.pid

COPY docker/frontend.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder --chown=appuser:appuser /app/dist /usr/share/nginx/html

USER appuser

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
