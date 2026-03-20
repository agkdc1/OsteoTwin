# Dashboard — Multi-stage build: Node for build, nginx for serving
FROM node:22-slim AS build

WORKDIR /app

# Install deps (cache layer)
COPY dashboard/package.json dashboard/package-lock.json* /app/
RUN npm ci --legacy-peer-deps

# Copy source and build
COPY dashboard/ /app/
RUN ./node_modules/.bin/vite build

# --- Production stage: nginx serves static files ---
FROM nginx:alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# nginx config (static only — API routing handled by Cloudflare Worker)
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
