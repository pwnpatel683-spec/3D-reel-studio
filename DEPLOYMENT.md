# ◈ 3D REEL STUDIO — Production Deployment & Operations Guide
### Phase 19: Live Production Deployment, Hosting Architecture & Operational Runbook

**Document Status**: Production Ready (`v1.0.0-rc1`)  
**Target Runtime**: Generic Linux / Docker Container / Cloud VM / Reverse Proxy  
**Hosting Target Status**: Deployment architecture prepared and verified; no live public cloud domain provisioned.  
**Revision Date**: 2026-10-05  

---

## 1. Production Architecture Overview

3D Reel Studio is architected as a high-performance, decoupled vertical video (9:16) transformation system designed for cloud container or Linux virtual machine environments:

```
                                  [ HTTPS Client / Mobile / Web ]
                                                 │
                                                 ▼
                                     [ Nginx / Cloud Proxy ]
                                        (TLS Termination)
                                  ┌──────────────┴──────────────┐
                                  │                             │
                        [ Static UI Assets ]           [ API Proxy /api/ ]
                      (HTML5 / CSS / Vanilla JS)                │
                                                                ▼
                                                   [ FastAPI ASGI Service ]
                                                   (Uvicorn 2+ Workers)
                                                                │
                            ┌───────────────────────────────────┼───────────────────────────────────┐
                            ▼                                   ▼                                   ▼
                   [ SQLite / PostgreSQL ]            [ Local Storage / Disk ]             [ System FFmpeg / OpenCV ]
                   (Relational State & Auth)         (Source, Frames, Final MP4)          (GrabCut, Audio, H.264/AAC)
```

- **Frontend Tier**: Pure Vanilla ES6 client, zero external runtime JS bundle requirements, responsive 9:16 preview canvas.
- **Backend Tier**: FastAPI asynchronous REST API with Pydantic v2 validation, JWT authentication, sliding-window rate limiting, and structured error handling.
- **Processing Engine**: Multithreaded worker manager executing synchronous pipeline stages:
  1. Chunked streaming media upload & storage isolation
  2. FFmpeg 16-bit 44.1kHz stereo audio extraction
  3. OpenAI Whisper AI speech-to-text with word timestamps (with offline fallback mock)
  4. Video scene change detection & keyframe extraction
  5. Multi-person face landmark detection & 17-point pose estimation
  6. 3D stylized comic generation with DALL-E 3 (with offline mock provider)
  7. Character identity consistency tracking with style anchors
  8. GrabCut / MediaPipe foreground character isolation & background adaptation
  9. Kinetic typography engine with soft alpha text-behind-character compositing
  10. Final 1080x1920 9:16 H.264/AAC MP4 video rendering with FFmpeg

---

## 2. Prerequisites & System Requirements

| Component | Minimum Specification | Recommended Production |
| :--- | :--- | :--- |
| **Operating System** | Linux (Ubuntu 22.04 LTS / Debian 12 / RHEL 9) | Linux (Ubuntu 22.04 LTS or Docker Base Image) |
| **CPU** | 2 Virtual Cores (x86_64 or arm64) | 4+ Cores (for parallel frame compositing & H.264 encoding) |
| **Memory (RAM)** | 4 GB RAM | 8 GB+ RAM |
| **Disk Storage** | 20 GB SSD | 50 GB+ High-IOPS SSD |
| **Python** | Python 3.11+ (Python 3.11, 3.12, 3.13) | Python 3.11 (as bundled in production Dockerfile) |
| **FFmpeg / FFprobe** | FFmpeg 5.0+ with `libx264`, `aac`, `libmp3lame` | FFmpeg 6.0+ / 7.0+ on system `$PATH` |

---

## 3. Production Environment Variables Reference

All production settings are configured through environment variables or a `.env` file (loaded via Pydantic `BaseSettings` in `app/core/config.py`).

| Variable Name | Production Default | Description | Required in Prod |
| :--- | :--- | :--- | :---: |
| `ENVIRONMENT` / `APP_ENV` | `production` | Application runtime environment. Setting `production` automatically disables `DEBUG`. | **Yes** |
| `DEBUG` | `false` | Disables debug stack traces and auto-reloading. | **Yes** |
| `HOST` | `0.0.0.0` | Bind interface for ASGI server. | **Yes** |
| `PORT` | `8000` | Bind port number for API service. | **Yes** |
| `DATABASE_URL` | `sqlite:///data/studio.db` | Connection string (`sqlite:///data/studio.db` or `postgresql://user:pass@host:5432/dbname`). | **Yes** |
| `DATA_DIR` | `data` | Directory for local database and schema files. | No |
| `MEDIA_STORAGE_ROOT` / `STORAGE_DIR` | `storage` | Persistent root directory for all project media assets. | **Yes** |
| `TEMP_STORAGE_ROOT` | `storage/temp` | Isolated directory for intermediate render frames. | No |
| `AUTH_SECRET` | *(Must be generated)* | Cryptographically random 256-bit secret used for HMAC-SHA256 JWT signing. | **Yes** |
| `AUTH_ALGORITHM` | `HS256` | Cryptographic algorithm for access tokens. | No |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | JWT expiration time (1440 minutes = 24 hours). | No |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `10` | Rate limit for sensitive authentication endpoints (`/login`, `/register`). | No |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | General rate limit per IP for protected project APIs. | No |
| `CORS_ALLOWED_ORIGINS` / `CORS_ORIGINS` | `["https://studio.yourdomain.com"]` | Whitelisted origin domains for web browsers. Wildcard `*` restricted in prod. | **Yes** |
| `OPENAI_API_KEY` | *(Secret Key)* | API key for Whisper AI transcription & DALL-E 3 comic generation. | Server-Only |
| `COMIC_GENERATION_PROVIDER` | `openai` | 3D comic styling generator: `openai` or `mock`. | No |
| `COMIC_GENERATION_MODEL` | `dall-e-3` | Model identifier for comic keyframe generation. | No |
| `SEGMENTATION_PROVIDER` | `opencv_guided` | Foreground segmentation engine (`opencv_guided` / `mock`). | No |
| `MAX_UPLOAD_SIZE` | `104857600` (100 MB) | Max file size accepted by upload endpoint in bytes. | No |
| `MAX_VIDEO_DURATION` | `600.0` (10 min) | Max input video duration allowed in seconds. | No |
| `PROCESSING_TIMEOUT` | `300` (5 min) | Subprocess and render execution hard timeout in seconds. | No |
| `MAX_CONCURRENT_RENDERS` | `2` | Bounded semaphore limit for concurrent 9:16 video renders. | No |
| `DOCS_ENABLED` | `false` | Controls whether `/docs` and `/openapi.json` are exposed. | No |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | No |

---

## 4. Secret Configuration & Random Secret Generation

The production `AUTH_SECRET` must **never** use default development values and must **never** be committed to source control.

### Generating a Secure 256-Bit Production Secret:
Run the following standard command on your deployment server:
```bash
# Using Python secrets module (Recommended)
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Or using OpenSSL
openssl rand -hex 32
```

Set the output in your production environment:
```bash
export AUTH_SECRET="your-generated-random-secret-key-here"
```

---

## 5. Database Setup (SQLite & PostgreSQL)

The system automatically initializes relational tables on startup and executes forward migrations.

### SQLite (Default Single-Node Deployment):
- Requires no external database daemon.
- Set `DATABASE_URL=sqlite:///data/studio.db`.
- Ensure directory `data/` has read/write permissions for the application user (`appuser:10001`).

### PostgreSQL (Multi-Worker / High-Concurrency Deployment):
1. Provision PostgreSQL 15+ database and user:
   ```sql
   CREATE USER reel_user WITH ENCRYPTED PASSWORD 'secure_production_password';
   CREATE DATABASE studio_db OWNER reel_user;
   GRANT ALL PRIVILEGES ON DATABASE studio_db TO reel_user;
   ```
2. Configure connection URL:
   ```bash
   export DATABASE_URL="postgresql://reel_user:secure_production_password@db.internal:5432/studio_db"
   ```

---

## 6. Migration Commands

Database migrations are tracked in `schema_migrations` and are idempotent and deterministic:

```bash
# Inspect current database migration status
python -m app.db.migrations status

# Apply pending schema migrations
python -m app.db.migrations migrate
```

---

## 7. Docker Build Instructions

The production [Dockerfile](file:///c:/Users/pwnma/OneDrive/Desktop/comic/Dockerfile) uses multi-stage Debian Bookworm Slim, installs system FFmpeg/OpenCV libraries, and runs as non-root user `appuser:10001`:

```bash
# Build the production Docker image
docker build -t reel-studio-api:v1.0.0 -f Dockerfile .
```

*Verification:*
```bash
# Verify image does not run as root
docker run --rm reel-studio-api:v1.0.0 whoami
# Output: appuser
```

---

## 8. Docker Run & Docker Compose Commands

### Running with Docker Compose (Recommended):
1. Prepare production configuration:
   ```bash
   cp .env.example .env
   # Edit .env and supply AUTH_SECRET, OPENAI_API_KEY, CORS_ALLOWED_ORIGINS
   ```
2. Launch stack:
   ```bash
   docker compose up -d --build
   ```
3. Inspect status and logs:
   ```bash
   docker compose ps
   docker compose logs -f reel-studio-api
   ```

### Running with Standalone Docker:
```bash
docker run -d \
  --name reel-studio-api \
  --restart unless-stopped \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e APP_ENV=production \
  -e DEBUG=false \
  -e AUTH_SECRET="your-strong-random-secret" \
  -e OPENAI_API_KEY="sk-your-openai-api-key" \
  -e CORS_ALLOWED_ORIGINS="https://studio.yourdomain.com" \
  -v reel-data:/app/data \
  -v reel-storage:/app/storage \
  reel-studio-api:v1.0.0
```

---

## 9. FFmpeg Requirements & Codec Verification

Production containers and host machines must have FFmpeg and FFprobe available on `$PATH`.

Verify installed codecs:
```bash
ffmpeg -version
ffprobe -version
ffmpeg -codecs | grep -E "libx264|libmp3lame|aac"
```

Required codec capabilities:
- Video Encoder: `libx264` (H.264)
- Audio Encoder: `aac` and `libmp3lame` (MP3)
- Pixel Format: `yuv420p`

---

## 10. Frontend Configuration

The Studio frontend is located in the root directory (`index.html`, `css/`, `js/`).

### Dynamic API Base URL Resolution:
In [js/api.js](file:///c:/Users/pwnma/OneDrive/Desktop/comic/js/api.js#L12-L16), the frontend automatically resolves the API Base URL in the following priority order:
1. `window.API_BASE_URL` or `window.__ENV__.API_BASE_URL` (injected via deployment script)
2. Meta tag: `<meta name="api-base-url" content="https://api.yourdomain.com">`
3. Current browser origin (`window.location.origin` when served behind reverse proxy)
4. Localhost fallback (`http://127.0.0.1:8000`) for development.

---

## 11. CORS Configuration

For production security, specify exact allowed frontend origins:
```bash
# Example for single domain:
export CORS_ALLOWED_ORIGINS="https://studio.yourdomain.com"

# Example for multiple domains:
export CORS_ALLOWED_ORIGINS="https://studio.yourdomain.com,https://app.yourdomain.com"
```
When `ENVIRONMENT=production`, wildcard `*` origins automatically restrict cookie credential propagation.

---

## 12. HTTPS & Reverse Proxy Setup (Nginx Example)

Production deployments must terminate TLS at the reverse proxy / load balancer.

```nginx
# HTTP -> HTTPS Redirect
server {
    listen 80;
    server_name studio.yourdomain.com;
    return 301 https://$host$request_uri;
}

# Production HTTPS Server
server {
    listen 443 ssl http2;
    server_name studio.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/studio.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/studio.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Static Frontend
    root /var/www/reelstudio;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API Proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 120M;
        proxy_read_timeout 360s;
        proxy_buffering off;
    }
}
```

---

## 13. Health & Readiness Monitoring

Configure Kubernetes / Docker health probes to use non-destructive diagnostic endpoints:

- **Liveness Probe**: `GET /api/v1/health/live`
  - Validates process responsiveness. Returns `HTTP 200` with `{"status": "healthy"}`.
- **Readiness Probe**: `GET /api/v1/health/ready`
  - Validates SQLite/PostgreSQL connectivity, local storage writeability, and FFmpeg binary resolution.
  - Returns `HTTP 200` with subsystem breakdown (`database`, `storage`, `ffmpeg`).
  - **Does NOT invoke paid AI provider APIs.**

---

## 14. Production Smoke Test Verification

Execute the automated Phase 18 production verification suite against the deployment:

```bash
cd backend
python -m tests.verify_phase18_deployment
```
*Expected Result:*
```text
============================================================
ALL 10 PRODUCTION DEPLOYMENT CHECKS COMPLETED SUCCESSFULLY!
============================================================
```

---

## 15. Backup & Disaster Recovery Procedures

1. **Database Backup**:
   - **SQLite**: Execute safe non-destructive snapshot:
     ```bash
     sqlite3 data/studio.db ".backup data/studio_backup_$(date +%Y%m%d_%H%M%S).db"
     ```
   - **PostgreSQL**: Standard logical dump:
     ```bash
     pg_dump -Fc -U reel_user -h localhost studio_db > /backup/studio_db_$(date +%Y%m%d).dump
     ```
2. **Media Storage Backup**:
   - Mirror `storage/projects/` directory to encrypted cold object storage (AWS S3 Glacier, Google Cloud Storage, or Azure Blob) nightly using `rclone` or `aws s3 sync`.
3. **Database Restore**:
   - SQLite: Replace `data/studio.db` with backup copy during container maintenance window.
   - PostgreSQL: `pg_restore -d studio_db /backup/studio_db.dump`.

---

## 16. Deployment Rollback Plan

- **Database Backward Compatibility**: Schema migrations in `app/db/migrations.py` are additive and idempotent. Reverting the backend container to a previous image tag does not cause schema incompatibility.
- **Media Asset Immutability**: Uploaded media and rendered MP4 files are named using deterministic UUIDs (`storage/projects/<project_id>/...`). Rolling back application containers leaves existing assets completely intact.

---

## 17. Operational Troubleshooting

| Symptom | Probable Root Cause | Resolution |
| :--- | :--- | :--- |
| `HTTP 401 UNAUTHORIZED` on API calls | Missing/expired Bearer token | Check user login status in UI; refresh access token. |
| `HTTP 404 NOT_FOUND` on project query | Project owned by different user ID | Verify user account matches project owner (IDOR protection). |
| `HTTP 413 CONTENT_TOO_LARGE` | Video exceeds `MAX_UPLOAD_SIZE` | Compress source video or increase `MAX_UPLOAD_SIZE` in `.env`. |
| `Readiness check warning: FFmpeg binary not resolved` | FFmpeg missing from `$PATH` | Install `ffmpeg` package via `apt-get` or Docker image. |
| Render hangs or times out | Video length exceeds timeout threshold | Check CPU resource allocation or increase `PROCESSING_TIMEOUT`. |
| `HTTP 429 TOO_MANY_REQUESTS` | Burst rate limit reached | Wait 60 seconds for in-memory sliding window to decay. |

---

## 18. Known Architecture Limitations

1. **Single-Node In-Memory Semaphore**: Background renders are queued and bounded locally via `ThreadPoolExecutor` (`MAX_CONCURRENT_RENDERS=2`). For multi-node distributed clusters, integrate a distributed queue (Celery / Redis / RabbitMQ) and shared networked storage (NFS / EFS).
2. **Local CPU/GPU Encoding**: Video compositing and H.264 rendering speed depends on host compute performance. For heavy volume, provision hardware-accelerated transcoding (NVENC / QuickSync).

---

## 19. GitHub Repository Setup & GitHub Actions CI/CD

The repository includes a comprehensive GitHub Actions workflow at [`.github/workflows/ci.yml`](file:///.github/workflows/ci.yml) that executes automated validation on every push and pull request.

### Configured CI Pipeline Stages:
1. **Security & Secrets Audit**: Scans checkout tree for accidentally committed `.env`, database (`.db`), or private key (`.pem`, `.key`) files.
2. **Backend Regression Test Suite**: Spawns Python 3.11 and 3.12 runners, installs system `ffmpeg` / `libgl1`, and executes the complete 172-test automated suite (`pytest backend/tests -v`).
3. **Frontend Static Asset Validation**: Validates existence and integrity of all HTML, CSS, and JS components, verifying dynamic `API_BASE_URL` resolution logic.
4. **Docker Image Build & Probe**: Builds the multi-stage production Docker image, confirms non-root execution (`appuser:10001`), verifies FFmpeg binary accessibility, boots a transient container, and asserts `HTTP 200` on `/api/v1/health/live` and `/api/v1/health/ready`.

### Required GitHub Repository Secrets (for deployment workflows):
| Secret Name | Purpose | Example Value |
| :--- | :--- | :--- |
| `AUTH_SECRET` | 256-bit token signing secret for production tests | *Generated random token* |
| `OPENAI_API_KEY` | Server-side OpenAI key for live transcription / DALL-E 3 | `sk-...` |
| `DOCKERHUB_USERNAME` | Container registry username (optional) | `myuser` |
| `DOCKERHUB_TOKEN` | Container registry auth token (optional) | `dckr_pat_...` |

---

## 20. Static Frontend Hosting Deployment Options

The frontend is a pure Vanilla ES6 Single-Page Application requiring zero Node.js build steps, making it compatible with any static hosting platform.

### Target Platforms:
- **GitHub Pages**: Deploy repository root (`index.html`, `css/`, `js/`) via GitHub Actions Pages workflow.
- **Cloudflare Pages / Netlify / Vercel**: Connect Git repository, set build command to empty/none, and publish root directory.
- **AWS S3 + CloudFront / GCP Cloud Storage**: Sync static files to storage bucket with public read and HTTPS CDN distribution.

### Configuring the Backend API URL:
In `index.html`, update the meta tag in `<head>`:
```html
<meta name="api-base-url" content="https://api.yourdomain.com">
```
Or inject window environment variable via hosting provider build hooks:
```html
<script>window.API_BASE_URL = "https://api.yourdomain.com";</script>
```

---

## 21. Ephemeral vs. Persistent Cloud Storage Architecture

The 3D Reel Studio pipeline processes large binary assets (raw MP4 uploads, extracted audio files, keyframe PNGs, character masks, and final 1080x1920 MP4 video reels).

| Hosting Platform Type | Storage Nature | Required Production Storage Solution |
| :--- | :--- | :--- |
| **Linux VPS / Dedicated Server** (DigitalOcean, Linode, EC2) | Persistent local NVMe/SSD | Mount Docker volume to host filesystem (`-v /var/data/studio:/app/storage`). |
| **Docker Compose / Swarm** | Named local volumes | Persisted in Docker named volume (`reel-storage:/app/storage`). |
| **Container as a Service (PaaS)** (Fly.io, Railway, Render) | Ephemeral container root | Attach persistent volume disk (e.g. Fly.io Volume `fly volumes create reel_storage --size 20GB`). |
| **Serverless Containers** (AWS ECS Fargate, GCP Cloud Run) | Strictly ephemeral | Mount AWS EFS (Elastic File System) / GCP Cloud Storage FUSE to `/app/storage`. |

> [!WARNING]
> **Data Loss Warning on Ephemeral Platforms**:
> If deploying to serverless container runtimes (such as standard Google Cloud Run or AWS Fargate) without an attached network filesystem, intermediate assets and rendered MP4 reels will be destroyed upon container scale-down or deployment restart.

---

## 22. Public Cloud Deployment Blockers & Prerequisites Checklist

To transition the application from a **Production-Ready Build** to a **Verified Public Live Deployment**, the following external cloud resources must be provisioned:

- [ ] **1. Cloud Compute Instance / Container Host**:
  - Provision a Linux VM (Ubuntu 22.04 LTS, 2+ vCPU, 4GB+ RAM) or Container Service (ECS / Cloud Run / Fly.io).
- [ ] **2. Domain Name & DNS Records**:
  - Register domain (e.g. `reelstudio.com`).
  - Configure `A` record pointing `api.reelstudio.com` to backend host IP.
  - Configure `CNAME` record pointing `app.reelstudio.com` to frontend static host.
- [ ] **3. SSL/TLS Certificate**:
  - Obtain Let's Encrypt certificate via `certbot` or enable Cloudflare SSL.
- [ ] **4. Production Secret Provisioning**:
  - Generate cryptographically secure `AUTH_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
  - Supply live `OPENAI_API_KEY` for Whisper and DALL-E 3 styling.
- [ ] **5. Ingress & Reverse Proxy**:
  - Deploy Nginx / Traefik with HTTP-to-HTTPS redirect and CORS headers.
- [ ] **6. Live Public Verification**:
  - Assert `curl -f https://api.yourdomain.com/api/v1/health/live` returns HTTP 200.
  - Execute end-to-end browser walkthrough on `https://app.yourdomain.com`.

