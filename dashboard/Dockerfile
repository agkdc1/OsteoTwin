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

# nginx template (envsubst replaces $PLANNING_API_URL, $SIMULATION_API_URL at startup)
COPY dashboard/nginx.conf /etc/nginx/templates/default.conf.template

# Cloud Run expects port 8080
EXPOSE 8080

# Default env vars (overridden by Cloud Run env)
ENV PLANNING_API_URL=http://localhost:8200
ENV SIMULATION_API_URL=http://localhost:8300

# Tell nginx envsubst to ONLY replace these two vars (not $uri, $host, etc)
ENV NGINX_ENVSUBST_TEMPLATE_SUFFIX=.template
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx/conf.d

CMD ["/bin/sh", "-c", "envsubst '${PLANNING_API_URL} ${SIMULATION_API_URL}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
