# ── Stage 1: Builder ──────────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

# Copy only package files first (layer caching trick)
COPY package*.json ./

# BuildKit cache mount: caches npm's download cache between builds
RUN --mount=type=cache,target=/root/.npm \
    npm ci --only=production

# Copy application source
COPY . .

# ── Stage 2: Production (Distroless) ─────────────────────────────
FROM gcr.io/distroless/nodejs20-debian12

WORKDIR /app

# Only copy what we need from the builder stage
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/index.js .

EXPOSE 3000
CMD ["index.js"]