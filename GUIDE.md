# Lab 02 — Multi-Stage Docker Build Optimization: Step-by-Step Guide

## Goal
Take a bloated ~1.2GB Node.js Docker image and reduce it to under 120MB using:
- Multi-stage builds
- Distroless base images
- BuildKit cache mounts
- `.dockerignore` configuration
- Automated CI size checks and vulnerability scanning via GitHub Actions + GHCR

---

## Prerequisites

Make sure the following are installed on your machine:

| Tool | Purpose |
|------|---------|
| Docker (with BuildKit) | Building and running containers |
| `dive` | Inspecting Docker image layers |
| `trivy` | Scanning images for vulnerabilities |
| GitHub account | For GitHub Actions CI and GHCR |

---

## Step 1 — Set Up the Node.js Application

Create a simple Node.js app that will serve as our starting point.

```bash
mkdir node-app && cd node-app
npm init -y
npm install express
```

**Why:** We need a real app with `node_modules` to simulate the bloat. `express` pulls in dependencies that make the image large — this is the realistic scenario you'll face in production.

Create `index.js`:

```js
const express = require('express');
const app = express();
app.get('/', (req, res) => res.send('Hello from optimized container!'));
app.listen(3000, () => console.log('Server running on port 3000'));
```

---

## Step 2 — Build the "Bloated" Single-Stage Image (Baseline)

Create a naive `Dockerfile.bloated`:

```dockerfile
FROM node:20
WORKDIR /app
COPY . .
RUN npm install
CMD ["node", "index.js"]
```

Build it:

```bash
docker build -f Dockerfile.bloated -t node-app:bloated .
```

Check the size:

```bash
docker images node-app:bloated
```

**Why:** This is your baseline. The full `node:20` image includes the entire OS, build tools (gcc, python, make), npm cache, and all dev dependencies — things you never need at runtime. This is what causes the ~1.2GB size.

---

## Step 3 — Create a `.dockerignore` File

```bash
cat > .dockerignore <<EOF
node_modules
npm-debug.log
.git
.env
*.md
Dockerfile*
EOF
```

**Why:** Without `.dockerignore`, Docker copies everything in your project directory into the build context — including `node_modules` (which can be hundreds of MBs), `.git` history, and local env files. This slows down builds and bloats the image. `.dockerignore` works exactly like `.gitignore` but for Docker.

---

## Step 4 — Write the Multi-Stage Dockerfile

Create `Dockerfile`:

```dockerfile
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
```

**Why each part matters:**

- `AS builder` — names the first stage so we can reference it later with `--from=builder`
- `COPY package*.json ./` before `COPY . .` — Docker caches layers. If your source code changes but `package.json` doesn't, Docker reuses the cached `npm ci` layer, saving minutes on rebuilds
- `--mount=type=cache,target=/root/.npm` — BuildKit feature that persists npm's download cache on the host between builds. Packages don't get re-downloaded every time
- `npm ci` instead of `npm install` — `ci` is faster, deterministic, and respects `package-lock.json` exactly. Ideal for CI/CD
- `--only=production` — skips devDependencies (test frameworks, linters, etc.) that have no place in a production image
- `gcr.io/distroless/nodejs20-debian12` — Google's distroless image contains only the Node.js runtime and nothing else. No shell, no package manager, no OS utilities. This eliminates an entire class of attack surface and dramatically reduces size
- `COPY --from=builder` — pulls only the compiled artifacts from Stage 1. Stage 1 itself is discarded and never ends up in the final image

---

## Step 5 — Build the Optimized Image

Enable BuildKit and build:

```bash
DOCKER_BUILDKIT=1 docker build -t node-app:optimized .
```

Compare sizes:

```bash
docker images | grep node-app
```

You should see something like:

```
node-app   optimized   ...   ~110MB
node-app   bloated     ...   ~1.2GB
```

**Why `DOCKER_BUILDKIT=1`:** BuildKit is Docker's modern build engine. It enables parallel stage execution, cache mounts (`--mount=type=cache`), and better layer caching. On Docker 23+, it's the default, but setting it explicitly ensures it's active on older versions.

---

## Step 6 — Inspect Layers with `dive`

```bash
# Install dive (Linux)
wget -q https://github.com/wagoodman/dive/releases/download/v0.12.0/dive_0.12.0_linux_amd64.deb
sudo apt install ./dive_0.12.0_linux_amd64.deb

# Analyse the image
dive node-app:optimized
```

**Why:** `dive` gives you an interactive breakdown of every layer in your image — what files were added, modified, or deleted at each step. It shows you "image efficiency" as a percentage and highlights wasted space. Use it to catch accidental large files, leftover build artifacts, or unnecessary cache files baked into layers.

Key things to look for in `dive`:
- Any layer adding files you don't recognise
- Large files that shouldn't be in production (e.g., `.git`, test fixtures)
- Efficiency score below 95% — investigate those layers

---

## Step 7 — Scan for Vulnerabilities with Trivy

```bash
# Install trivy (Linux)
sudo apt-get install wget apt-transport-https gnupg -y
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb generic main" | sudo tee /etc/apt/sources.list.d/trivy.list
sudo apt-get update && sudo apt-get install trivy -y

# Scan the optimized image
trivy image node-app:optimized

# Scan and fail if HIGH or CRITICAL CVEs are found
trivy image --exit-code 1 --severity HIGH,CRITICAL node-app:optimized
```

**Why:** Smaller images have fewer CVEs because there's less software to exploit. Distroless images in particular have dramatically fewer vulnerabilities than full OS images. `--exit-code 1` makes trivy return a non-zero exit code on findings — this is what you'll use in CI to fail the pipeline when vulnerabilities are detected.

---

## Step 8 — Push to GitHub Container Registry (GHCR)

GitHub no longer supports password authentication for Docker. Authentication is done via a **Personal Access Token (PAT)**.

Generate a PAT at `github.com → Settings → Developer settings → Personal access tokens` with `write:packages` scope, then authenticate:

```bash
echo YOUR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

Tag and push:

```bash
docker tag node-app:optimized ghcr.io/YOUR_GITHUB_USERNAME/node-app:latest
docker push ghcr.io/YOUR_GITHUB_USERNAME/node-app:latest
```

> **Preferred approach:** Skip manual login entirely and let GitHub Actions handle authentication (Step 9). The `GITHUB_TOKEN` is auto-injected per workflow run — no PAT management, no expiry issues.

---

## Step 9 — Automate with GitHub Actions

Create `.github/workflows/docker.yml`:

```yaml
name: Build, Scan & Push

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build-and-scan:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
        # Buildx enables BuildKit features (cache mounts, multi-platform, etc.)

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
          # GITHUB_TOKEN is auto-provided by Actions — no manual secret needed

      - name: Build image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false          # build only, don't push yet (scan first)
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
          cache-from: type=gha  # use GitHub Actions cache for layers
          cache-to: type=gha,mode=max
          load: true            # load into local Docker daemon for scanning

      - name: Check image size (regression gate)
        run: |
          SIZE=$(docker inspect ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest \
            --format='{{.Size}}')
          MAX_SIZE=$((120 * 1024 * 1024))  # 120MB in bytes
          echo "Image size: $((SIZE / 1024 / 1024))MB"
          if [ "$SIZE" -gt "$MAX_SIZE" ]; then
            echo "❌ Image exceeds 120MB size limit!"
            exit 1
          fi
          echo "✅ Image size is within limit"

      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
          format: table
          exit-code: '1'
          severity: HIGH,CRITICAL

      - name: Push to GHCR
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**Why each CI step matters:**

- `setup-buildx-action` — installs Docker Buildx so BuildKit features work in CI
- `cache-from/cache-to: type=gha` — stores Docker layer cache in GitHub Actions cache storage. Subsequent runs reuse cached layers, cutting build time significantly
- `push: false` + `load: true` — builds the image locally in the CI runner first so we can inspect and scan it before pushing anything to the registry
- Size check — a shell script that uses `docker inspect` to get the exact byte size and fails the pipeline if it exceeds 120MB. This is your regression gate — it prevents future PRs from accidentally bloating the image
- Trivy scan before push — vulnerabilities are caught before the image ever reaches the registry
- `if: github.ref == 'refs/heads/main'` — only pushes to GHCR on merges to main, not on every PR

---

## Summary: What Changed and Why It Works

| Technique | Size Impact | Why It Works |
|-----------|------------|--------------|
| Multi-stage build | Removes ~800MB | Build tools and intermediate files never enter the final image |
| Distroless base image | Removes ~200MB | No OS shell, utilities, or package manager in the runtime image |
| `--only=production` | Removes devDeps | Test/lint tools have no place in production |
| `.dockerignore` | Speeds up build | Reduces build context sent to Docker daemon |
| BuildKit cache mounts | Faster rebuilds | npm packages cached on host, not re-downloaded |
| Layer ordering (deps before src) | Faster rebuilds | Unchanged dependency layers are reused from cache |

**End result:** ~1.2GB → ~110MB (≈90% reduction)

---

## Troubleshooting

**`--mount=type=cache` not working:**
Make sure BuildKit is enabled: `export DOCKER_BUILDKIT=1`

**Distroless image has no shell for debugging:**
Use the debug variant temporarily: `gcr.io/distroless/nodejs20-debian12:debug` — it includes busybox. Never use this in production.

**Trivy failing with network errors in CI:**
Add `--skip-db-update` if the vulnerability DB download is blocked, or pre-cache it as a CI artifact.

**GHCR push permission denied:**
Ensure the Actions job has `permissions: packages: write` and the PAT/GITHUB_TOKEN has `write:packages` scope.
