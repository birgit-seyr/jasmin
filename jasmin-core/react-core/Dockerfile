# syntax=docker/dockerfile:1.6
# =============================================================================
# Jasmin React frontend - multi-stage build
#   Stages:
#     deps    - npm ci against package*.json only (cached layer)
#     dev     - vite dev server with HMR
#     builder - produces /app/dist
#     nginx   - production: serves /app/dist via nginx
# =============================================================================

ARG NODE_VERSION=22

# -----------------------------------------------------------------------------
# deps - cached node_modules layer
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS deps

WORKDIR /app
RUN apk add --no-cache python3 make g++ libc6-compat

COPY package.json package-lock.json* ./
RUN npm ci


# -----------------------------------------------------------------------------
# dev - vite dev server (source bind-mounted at runtime by compose)
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS dev

WORKDIR /app
ENV NODE_ENV=development \
    CHOKIDAR_USEPOLLING=true

COPY --from=deps /app/node_modules ./node_modules
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]


# -----------------------------------------------------------------------------
# builder - produces /app/dist for production
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /app
ENV NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Empty baseURL: orval-generated paths already start with /api/, so a "/api"
# default would double-prefix to /api/api/... and 404 everything behind the
# gateway. compose passes VITE_API_URL="" explicitly; keep the image default
# aligned for direct ``docker build`` too.
ARG VITE_API_URL=
ARG VITE_APP_NAME="Jasmin Platform"
# Sentry DSN gets baked into the bundle at build time (Vite resolves
# ``import.meta.env.VITE_*`` statically). Empty value -> SDK no-op.
ARG VITE_SENTRY_DSN=""
# Super-admin/platform subdomain — baked into the bundle (superAdminHost.ts).
# Must be a build ARG or it silently defaults to "marillen" in every build.
ARG VITE_SUPER_ADMIN_SUBDOMAIN=marillen
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_APP_NAME=${VITE_APP_NAME} \
    VITE_SENTRY_DSN=${VITE_SENTRY_DSN} \
    VITE_SUPER_ADMIN_SUBDOMAIN=${VITE_SUPER_ADMIN_SUBDOMAIN}

RUN npm run build


# -----------------------------------------------------------------------------
# nginx - production runtime
# -----------------------------------------------------------------------------
FROM nginx:1.31-alpine AS nginx

# Replace default site with our SPA-friendly config
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Built SPA
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
