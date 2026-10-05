# ◈ 3D REEL STUDIO — Phase 1 through Phase 14 Complete

**3D REEL STUDIO** is a professional AI video transformation platform engineered to transform ordinary user videos into personalized 3D comic-style vertical Reels using modern AI models, reference-guided consistency engines, layered foreground/background decomposition, and synchronized kinetic typography composited behind the primary subject.

> **PROJECT STATUS**:
> - **Phase 1 (Complete)**: Professional Frontend & Studio UI Foundation (HTML5, CSS3, Vanilla JS).
> - **Phase 2 (Complete)**: FastAPI Backend Foundation, API Versioning (`/api/v1`), Health & Readiness Probes, Structured Error Handling, and Frontend Integration.
> - **Phase 3 (Complete)**: SQLite Database Persistence with SQLAlchemy (`Project`, `MediaFile`, `TransformationJob` models), Project CRUD API, and Studio Modal Integration.
> - **Phase 4 (Complete)**: Multipart Source Video & Face Reference Media Upload, Secure Project-Isolated Storage, and SHA-256 Checksums.
> - **Phase 5 (Complete)**: FFmpeg Audio Extraction Pipeline (`POST /api/v1/projects/{project_id}/media/{media_id}/extract-audio`) transcoding source video to high-fidelity MP3 (`libmp3lame`, 44.1kHz, 192k) with audio stream validation and persistent `extracted_audio` MediaFile records.
> - **Phase 6 (Complete)**: AI Audio Transcription & Timestamp Persistence (`POST /api/v1/projects/{project_id}/media/{media_id}/transcribe`) via OpenAI Whisper (`whisper-1`) with detected language, segmented timestamps, word-level synchronization data, SQLite persistence (`Transcript`, `TranscriptSegment`), and Studio UI Transcript panel.
> - **Phase 7 (Complete)**: Video Scene & Content Analysis (`POST /api/v1/projects/{project_id}/media/{media_id}/analyze`) extracting stream metadata (width, height, FPS, frame count, duration, codec, aspect ratio), detecting scene cuts (`select='gt(scene,0.3)',showinfo`), extracting midpoint visual keyframes to project storage (`keyframes/`), SQLite persistence (`VideoAnalysis`, `VideoScene`, `SceneKeyframe`), and Studio UI Scenes inspector panel.
> - **Phase 8 (Complete)**: Face Detection, Identity Reference & Body Pose Tracking (`POST /api/v1/projects/{project_id}/media/{media_id}/vision-analysis`) extracting normalized face bounding boxes & 5 facial landmarks, selecting deterministic primary subjects, filtering and saving face reference crops (`storage/projects/{id}/face-reference/`), estimating 17-point COCO/MediaPipe body pose skeletons, spatial temporal tracking across video keyframes, SQLite persistence (`VisionAnalysis`, `DetectedSubject`, `FaceDetection`, `FaceReference`, `PoseDetection`, `PoseLandmark`), and Studio UI Vision & Pose panel with live canvas overlays.
> - **Phase 9 (Complete)**: 3D Comic Style Generation (`POST /api/v1/projects/{project_id}/comic-generation`) transforming analyzed scene keyframes into stylized 9:16 vertical 3D comic frames (`1024x1792`). Features provider/model agnostic abstraction (`ComicGenerationProvider`), OpenAI DALL-E 3 (`dall-e-3`) provider with base64 decoding, local deterministic `MockComicProvider` for fallback & cost-free unit testing, controlled prompt synthesis preserving subject pose, clothing, and facial characteristics, SQLite persistence (`ComicGeneration`, `ComicFrame`), secure project media storage (`comic-frames/`), and Studio UI side-by-side comparison cards (ORIGINAL vs 3D COMIC).
> - **Phase 10 (Complete)**: Identity + Temporal Consistency Engine (`POST /api/v1/projects/{project_id}/consistency/profile` & `POST /api/v1/projects/{project_id}/consistency/generate`). Features canonical visual reference selection from Phase 8 face references, multi-angle reference sorting without fabrication, stable non-sensitive character descriptors, versioned style-locking (`v1-3d-comic-lock`), sequential temporal frame chaining (`previous_frame_id`), non-identifying OpenCV visual diagnostics (face localization & color histogram correlation), non-destructive Phase 9 provenance, per-frame regeneration controls, SQLite persistence (`CharacterConsistencyProfile`, `ConsistencyGeneration`, `ConsistentComicFrame`), secure storage (`consistent-frames/`), and Studio UI 3-way comparisons (ORIGINAL → PHASE 9 COMIC → PHASE 10 CONSISTENT COMIC).
> - **Phase 11 (Complete)**: Foreground Segmentation & Dynamic Background Layering (`POST /api/v1/projects/{project_id}/segmentation`). Features provider-agnostic segmentation (`ForegroundSegmentationProvider`), subject-guided GrabCut segmentation seeded by Phase 8 face location and 17-point pose skeleton priors, morphological refinement (hole-filling, edge smoothing, alpha feathering), clean background inpainting (`cv2.inpaint` Telea), adaptive background styling (`ORIGINAL`, `SOFT_BLUR`, `DEPTH_STYLE`, `COMIC_STYLE`), independent layer asset generation (transparent RGBA foreground, binary/soft mask, styled background, alpha composite preview), non-destructive reprocessing, SQLite persistence (`SegmentationResult`), secure project media storage (`segmentation/`), and Studio UI 4-way layer inspection panel.
> - **Phase 13 (Complete)**: Final Video Compositing & 9:16 Reel Rendering (`POST /api/v1/projects/{project_id}/render`, `GET /.../render`, `GET /.../render/{id}`, `POST /.../render/{id}/cancel`). Integrates all pipeline outputs into a vertical 9:16 MP4 Reel (1080×1920 preferred, H.264 `libx264` video, AAC `aac` audio). Features scene timeline assembly, dynamic multi-frame kinetic text-behind-character compositing, seamless concatenation, audio multiplexing with `-movflags +faststart`, ffprobe output validation (resolution, codec, duration tolerance), non-destructive SQLite persistence (`RenderJob`, `MediaFile`), isolated temporary working directory cleanup, and Studio UI Output panel with in-app video playback player and secure direct MP4 download.

---

## 🎨 Design System & Visual Language

- **Primary Colors**:
  - Background: `#0b0c10`
  - Neon Red: `#ff2e63`
  - Cyber Cyan: `#00fff5`
- **Typography**: `Outfit` (Headings & UI elements) and `JetBrains Mono` (Telemetry & technical specs).
- **Aesthetic**: Cyberpunk dark studio aesthetic with frosted glass cards, high contrast, and clean layout balance.

---

## 📁 Project Structure

```
comic/
├── index.html                  # Master Studio HTML5 interface (Transcript, Scenes, Vision, 3D Comic, Consistency, Layers & BG, Kinetic Lyrics, Output & Final Reel Render panels)
├── css/
│   ├── main.css                # Core design system tokens, typography, and grid
│   ├── studio.css              # Left (Create) and Right (Inspector) studio panels, Layer & Kinetic Lyrics inspection grid, Reel player
│   ├── canvas.css              # Center 9:16 vertical workspace & player overlay
│   ├── pipeline.css            # 11-stage pipeline timeline & terminal drawer
│   └── components.css          # Switches, toasts, modals, transcript, scene, face ref, 3D comic, consistency & segmentation cards
├── js/
│   ├── api.js                  # API client (Projects, Uploads, Audio, Transcription, Scenes, Vision, Comic Gen, Consistency, Segmentation, Lyrics, Render)
│   ├── state.js                # Centralized reactive appState object
│   ├── canvas.js               # Canvas typography & live vision bounding box + pose skeleton overlays
│   ├── pipeline.js             # Pipeline node renderer and telemetry log
│   ├── ui.js                   # Modals, tabs, toast notification system, shortcuts
│   └── app.js                  # Studio orchestrator, upload orchestration & analysis/generation/consistency/segmentation/lyrics/render pipelines
├── backend/                    # FastAPI Backend Service
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint, lifespan (init_db), exception handlers
│   │   ├── api/v1/             # API v1 routes (health, ready, projects, media, transcribe, analyze, vision, comic-gen, consistency, segmentation, lyrics, render)
│   │   ├── core/               # Pydantic Settings (OPENAI_API_KEY, SEGMENTATION_PROVIDER, storage limits) & logger
│   │   ├── db/                 # SQLAlchemy engine, session generator, init_db
│   │   ├── models/             # Project, MediaFile, Transcript, VideoAnalysis, VisionAnalysis, ComicGeneration, CharacterConsistencyProfile, ConsistentComicFrame, SegmentationResult, LyricStyle, LyricAnimation, LyricSegment, LyricPreview, RenderJob
│   │   ├── schemas/            # Request & response models
│   │   └── services/           # Storage, FFmpeg Audio, OpenAI Whisper, Scene Analysis, Vision, Comic Generation, Consistency Engine, Segmentation Engine, Kinetic Lyrics Engine, Reel Rendering Engine
│   ├── data/                   # SQLite database storage (studio.db)
│   ├── storage/                # Project media storage (source/, face-reference/, audio/, keyframes/, comic-frames/, consistent-frames/, segmentation/, lyrics/, final/)
│   ├── tests/                  # Automated Pytest suite (122 passing tests)
│   ├── requirements.txt        # Backend dependencies (OpenCV, Pillow, NumPy, OpenAI)
│   ├── .env.example            # Backend environment template
│   └── README.md               # Backend documentation
├── .env.example                # Root environment template
└── README.md                   # Workspace documentation
```

---

## 🎬 Final Video Compositing & 9:16 Reel Rendering (Phase 13)

Phase 13 integrates all upstream pipeline outputs into a finished vertical 9:16 MP4 video ready for social Reel playback:

```text
Source Video Timing
      ↓
Scene Breakdown (Phase 7)
      ↓
Consistent 3D Comic Visuals (Phase 10)
      ↓
Foreground Character + Background Decomposition (Phase 11)
      ↓
Kinetic Lyrics with Occlusion (Phase 12)
      ↓
Layered Scene Frame Compositing (Layer 0: BG → Layer 1: TEXT → Layer 2: FG Character)
      ↓
FFmpeg Scene Clips Generation & Concatenation
      ↓
Original Audio Multiplexing (Phase 5 AAC Transcode)
      ↓
FFprobe Output Validation (1080x1920, H.264, AAC, Duration Tolerance)
      ↓
Persistent Final MediaFile Storage & In-App Reel Playback + Secure Download
```

### 1. Final Output Specifications
- **Container**: `MP4`
- **Resolution**: `1080 × 1920` (Strict 9:16 vertical ratio)
- **Video Codec**: `H.264 / libx264` (`yuv420p`, `-crf 18`, `-preset medium`)
- **Audio Codec**: `AAC` (`-c:a aac`, `-b:a 192k`, `-ar 44100`)
- **Frame Rate**: Source FPS (or default 30 FPS)
- **FastStart**: `-movflags +faststart` enabled for instant streaming/playback.

### 2. Render Endpoints
- `POST /api/v1/projects/{project_id}/render`: Initiates final reel rendering with safe defaults, idempotency check, and force re-render support.
- `GET /api/v1/projects/{project_id}/render`: Lists all render jobs and returns the latest successful render.
- `GET /api/v1/projects/{project_id}/render/{render_id}`: Fetches specific render job details and progress.
- `POST /api/v1/projects/{project_id}/render/{render_id}/cancel`: Safely cancels an active render job and cleans temporary assets.

---

## 🧪 Testing

Run the full automated test suite across all phases:
```bash
pytest backend/tests -v
```

- `WORD_BY_WORD`: Sequential word-level opacity and scale emphasis.

### 4. Normalized Positioning & Safe Wrapping
- Normalized coordinate mapping (`x: 0.0 -> 1.0`, `y: 0.0 -> 1.0`) ensuring 100% resolution independence across vertical 9:16 canvases (`1080x1920`, `1024x1792`).
- Safe margins and automated text wrapping preventing text overflow outside reel-safe viewport zones.

### 5. Preview Endpoint Specification
```bash
POST /api/v1/projects/{project_id}/lyrics/preview
Content-Type: application/json
{
  "timestamp": 2.15,
  "lyric_segment_id": "lyric-seg-uuid-1",
  "position_y": 0.75,
  "position_x": 0.5,
  "scale": 1.0,
  "opacity": 1.0
}
```

---

## 🧪 Testing

Run the full automated test suite (**113 passing tests covering Phases 1–12**):
```bash
pytest backend/tests -v
```

> **IMPORTANT SCOPE NOTE**: Phase 12 focuses exclusively on kinetic typography layout, motion calculation, soft alpha occlusion behind the character, and timestamp preview generation. Final FFmpeg MP4 encoding, audio remuxing, and video export are scheduled for the next phase.


---

## 🎨 Design System & Visual Language

- **Primary Colors**:
  - Background: `#0b0c10`
  - Neon Red: `#ff2e63`
  - Cyber Cyan: `#00fff5`
- **Typography**: `Outfit` (Headings & UI elements) and `JetBrains Mono` (Telemetry & technical specs).
- **Aesthetic**: Cyberpunk dark studio aesthetic with frosted glass cards, high contrast, and clean layout balance.

---

## 📁 Project Structure

```
comic/
├── index.html                  # Master Studio HTML5 interface (Transcript, Scenes, Vision, 3D Comic, Consistency, Layers & BG panels)
├── css/
│   ├── main.css                # Core design system tokens, typography, and grid
│   ├── studio.css              # Left (Create) and Right (Inspector) studio panels & Layer inspection grid
│   ├── canvas.css              # Center 9:16 vertical workspace & player overlay
│   ├── pipeline.css            # 11-stage pipeline timeline & terminal drawer
│   └── components.css          # Switches, toasts, modals, transcript, scene, face ref, 3D comic, consistency & segmentation cards
├── js/
│   ├── api.js                  # API client (Projects, Uploads, Audio, Transcription, Scenes, Vision, Comic Gen, Consistency, Segmentation)
│   ├── state.js                # Centralized reactive appState object
│   ├── canvas.js               # Canvas typography & live vision bounding box + pose skeleton overlays
│   ├── pipeline.js             # Pipeline node renderer and telemetry log
│   ├── ui.js                   # Modals, tabs, toast notification system, shortcuts
│   └── app.js                  # Studio orchestrator, upload orchestration & analysis/generation/consistency/segmentation pipelines
├── backend/                    # FastAPI Backend Service
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint, lifespan (init_db), exception handlers
│   │   ├── api/v1/             # API v1 routes (health, ready, projects, media, transcribe, analyze, vision, comic-gen, consistency, segmentation)
│   │   ├── core/               # Pydantic Settings (OPENAI_API_KEY, SEGMENTATION_PROVIDER, storage limits) & logger
│   │   ├── db/                 # SQLAlchemy engine, session generator, init_db
│   │   ├── models/             # Project, MediaFile, Transcript, VideoAnalysis, VisionAnalysis, ComicGeneration, CharacterConsistencyProfile, ConsistentComicFrame, SegmentationResult
│   │   ├── schemas/            # Request & response models
│   │   └── services/           # Storage, FFmpeg Audio, OpenAI Whisper, Scene Analysis, Vision, Comic Generation, Consistency Engine, Segmentation Engine
│   ├── data/                   # SQLite database storage (studio.db)
│   ├── storage/                # Project media storage (source/, face-reference/, audio/, keyframes/, comic-frames/, consistent-frames/, segmentation/)
│   ├── tests/                  # Automated Pytest suite (102 passing tests)
│   ├── requirements.txt        # Backend dependencies (OpenCV, Pillow, NumPy, OpenAI)
│   ├── .env.example            # Backend environment template
│   └── README.md               # Backend documentation
├── .env.example                # Root environment template
└── README.md                   # Workspace documentation
```

---

## 🎭 Foreground Segmentation & Dynamic Background (Phase 11)

Phase 11 isolates the primary character from consistent comic frames and creates independently compositable scene layers:

### 1. Architecture & Provider
- **Abstraction**: `ForegroundSegmentationProvider` interface with conceptual `segment_foreground(image, subject_bbox, pose_landmarks)` operation.
- **Provider Implementation**: `OpenCVSubjectGuidedSegmentationProvider` using iterative GrabCut initialized with Phase 8 face bounding box and 17-point pose skeleton priors. Face core and spine landmarks are marked as definitive foreground seeds to eliminate background false-positives without requiring heavy multi-gigabyte weights.
- **Test Provider**: `MockSegmentationProvider` for deterministic, offline testing.

### 2. Supported Background Adaptation Modes
- `ORIGINAL`: Preserves source scene environment context cleanly inpainted behind the character.
- `SOFT_BLUR`: Applies Gaussian depth-of-field blur (`kernel=31, sigma=15.0`) to focus visual priority on the 3D character.
- `DEPTH_STYLE`: Applies radial gradient vignette lighting and contrast curve adjustments to emphasize scene depth.
- `COMIC_STYLE`: Applies bilateral smoothing filter with high-contrast ink contour lines and +20% color saturation to match the 3D comic aesthetic.

### 3. Mask Refinement & Quality Metrics
- Morphological closing (`MORPH_CLOSE`) and hole-filling via contour hierarchy.
- Small island noise removal below area threshold.
- Configurable Gaussian edge feathering (`alpha_feather_radius`, default 3px) for smooth anti-aliased alpha blending.
- Real-time calculated quality metrics: `foreground_coverage_ratio`, `edge_smoothness_ratio`, and composite `quality_score`.

### 4. Background Inpainting
- Inpaints the foreground character mask on the source scene using Fast Marching Telea inpainting (`cv2.inpaint`) to avoid ghost subject duplication.

### 5. Configuration Settings
```env
SEGMENTATION_PROVIDER=opencv_guided    # or "mock"
SEGMENTATION_MODEL=grabcut_pose_prior
SEGMENTATION_DEFAULT_BG_MODE=ORIGINAL # ORIGINAL | SOFT_BLUR | DEPTH_STYLE | COMIC_STYLE
```

### 6. Known Limitations
- **Fine Hair Matting**: Extremely wispy semi-transparent hair strands on complex backgrounds may exhibit minor edge clamping due to GrabCut bounding.
- **Extreme Occlusions**: Complex hands holding background objects may require edge feathering adjustments.
- **Extreme Lighting Variations**: Very dark characters against very dark backgrounds may have reduced contrast boundary sharpness.

---

## 🔑 OpenAI & Provider Configuration (Phase 9 & 10)

Comic generation and character consistency support both OpenAI DALL-E 3 and local Mock generation:

```env
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_TRANSCRIPTION_MODEL=whisper-1
COMIC_GENERATION_PROVIDER=mock   # or "openai" for DALL-E 3
COMIC_GENERATION_MODEL=dall-e-3
```

> **SECURITY NOTE**: `OPENAI_API_KEY` is kept strictly backend-side and is never exposed in client JavaScript, HTTP response bodies, or logs.

---

## 🛠️ FFmpeg Setup & Configuration

FFmpeg and FFprobe are required system dependencies for audio extraction, video metadata probing, scene shot cut detection, and visual keyframe image extraction.

### 1. Installation
- **Windows (WinGet)**: `winget install Gyan.FFmpeg.Essentials`
- **macOS (Homebrew)**: `brew install ffmpeg`
- **Linux (Debian/Ubuntu)**: `sudo apt-get update && sudo apt-get install -y ffmpeg`

### 2. Verify Installation
```bash
ffmpeg -version
ffprobe -version
```

---

## 🚀 How to Run Locally

### 1. Start the FastAPI Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```
API Documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 2. Launch the Studio Frontend
Open `index.html` in your browser, or serve it via Python:
```bash
python -m http.server 8080
```
Navigate to `http://localhost:8080`.

---

## 🔄 End-to-End Processing Flow (Phases 4 through 11)

```text
Original Video (.mp4 / .mov / .webm)
               │
               ▼
[POST /api/v1/projects/{project_id}/media] (media_type=source_video)
               │
               ├─────────────────────────────────────────────┐
               ▼                                             ▼
[POST /.../extract-audio]                   [POST /.../analyze]
               │                                             │
               ▼                                             ▼
[FFmpeg MP3 Transcode]                      [FFprobe Stream Metadata & Scene Cuts]
[storage/projects/<id>/audio/*.mp3]         [storage/projects/<id>/keyframes/*.jpg]
               │                                             │
               ▼                                             ▼
[POST /.../transcribe]                      [POST /.../vision-analysis]
               │                                             │
               ▼                                             ▼
[OpenAI Whisper API]                        [Face BBoxes + 17-pt Pose + Face Refs]
[SQLite: Transcript & Segments]             [storage/projects/<id>/face-reference/*.jpg]
                                                             │
                                                             ▼
                                            [POST /.../comic-generation]
                                                             │
                                                             ▼
                                            [Phase 9: 3D Comic Frames]
                                            [storage/projects/<id>/comic-frames/*.png]
                                                             │
                                                             ▼
                                            [POST /.../consistency/generate]
                                                             │
                                                             ▼
                                            [Phase 10: Canonical Ref Selection]
                                            [Stable Style Lock & Descriptors]
                                            [Sequential Temporal Chaining]
                                            [storage/projects/<id>/consistent-frames/*.png]
                                                             │
                                                             ▼
                                            [POST /.../segmentation]
                                                             │
                                                             ▼
                                            [Phase 11: Subject-Guided GrabCut]
                                            [Pose + Face Prior Foreground Mask]
                                            [Morphological Refinement & Feathering]
                                            [Clean Background Telea Inpainting]
                                            [Adaptive Background Styling: ORIGINAL/BLUR/DEPTH/COMIC]
                                            [RGBA Foreground + Alpha Mask + Background + Composite]
                                            [storage/projects/<id>/segmentation/*]
```

- **Phase 14 (Complete)**: Production Hardening, Security, Storage Diagnostics & Recovery. Enforces configurable media limits (duration, resolution, FPS, size), strict path traversal defenses, safe argument arrays (no `shell=True`), timeout protections across all FFmpeg and external provider calls, startup stale job reconciliation (`reconcile_stale_jobs_on_startup`), non-destructive diagnostic storage audit (`GET /projects/{id}/storage-audit`), dry-run safe cleanup (`POST /projects/{id}/storage-cleanup`), in-flight concurrency duplicate protection, and automated test suite with **135 passing tests**.

---

## 🛡️ Production Hardening & Security Architecture (Phase 14)

### 1. Configurable Media Limits
| Resource | Production Limit | Config Variable | Error Code |
|---|---|---|---|
| Max Video Upload Size | `100 MB` | `MAX_VIDEO_UPLOAD_SIZE_BYTES` | `FILE_TOO_LARGE` |
| Max Image Upload Size | `15 MB` | `MAX_IMAGE_UPLOAD_SIZE_BYTES` | `FILE_TOO_LARGE` |
| Max Video Duration | `600 seconds` (10 min) | `SOURCE_VIDEO_MAX_DURATION_SECONDS` | `VIDEO_DURATION_EXCEEDED` |
| Max Video Resolution | `3840 × 3840` (4K UHD) | `SOURCE_VIDEO_MAX_WIDTH` / `HEIGHT` | `VIDEO_RESOLUTION_EXCEEDED` |
| Max Frame Rate | `120.0 FPS` | `SOURCE_VIDEO_MAX_FPS` | `VIDEO_FPS_EXCEEDED` |
| Max Scene Count Limit | `100 scenes` | `MAX_SCENE_COUNT_LIMIT` | `SCENE_LIMIT_EXCEEDED` |

### 2. Security Defense Model
- **Strict Path Traversal Prevention**: Project IDs, media IDs, and subpaths are validated against directory traversal sequences (`..`, `/`, `\`, leading dots). Physical storage paths are validated using `.resolve()` and must strictly start within the configured root storage directory.
- **Safe Subprocess Execution**: All FFmpeg, FFprobe, and system commands are executed with explicit argument arrays (`shell=False`). No user input is interpolated into shell commands.
- **Credential & API Key Isolation**: API keys are strictly backend-only. Error handlers sanitize stack traces and internal filesystem paths from API responses.
- **CORS Protection**: In production mode, wildcard credentials with `allow_origins=["*"]` are disabled.

### 3. Job State Lifecycle & Startup Reconciliation
- **Job States**: `queued` → `processing` → `completed`, `failed`, or `cancelled`. Invalid state transitions are prevented.
- **Duplicate Job Protection**: Triggering a long-running operation (transcription, render) while an identical job is currently in `processing` or `queued` status returns the existing in-flight job rather than spawning redundant tasks.
- **Server Restart Recovery**: The FastAPI `lifespan` startup hook automatically executes `reconcile_stale_jobs_on_startup(db)`. Any background jobs left in `processing` or `queued` state from an ungraceful crash or restart are transitioned to `failed` with error code `SERVER_RESTARTED_RECOVERY`.

### 4. Storage Diagnostics & Safe Cleanup
- **Diagnostic Storage Audit** (`GET /api/v1/projects/{project_id}/storage-audit`):
  Non-destructive inspection validating database `MediaFile` records against physical files, identifying missing files, zero-byte corruptions, SHA-256 checksum mismatches, unreferenced files, and abandoned temporary directories.
- **Storage Cleanup Maintenance** (`POST /api/v1/projects/{project_id}/storage-cleanup`):
  Safely removes abandoned render temporary folders (`tmp_job_*`) or unreferenced orphaned files. **Defaults to `dry_run=True`** so no files are modified without explicit confirmation.

### 5. Timeouts & Bounded Retries
- **FFmpeg Transcoding**: `FFMPEG_TIMEOUT_SECONDS = 180s`
- **Render Pipeline**: `RENDER_TIMEOUT_SECONDS = 300s`
- **AI Transcription**: `TRANSCRIPTION_TIMEOUT_SECONDS = 60s` (OpenAI Whisper with max 2 retries)
- **3D Comic Generation**: `COMIC_GENERATION_TIMEOUT_SECONDS = 60s` (OpenAI DALL-E 3 with max 2 retries)
- **Foreground Segmentation**: `SEGMENTATION_TIMEOUT_SECONDS = 60s`

---

## 🩺 System Health & Readiness Endpoints

- **Liveness Probe**: `GET /api/v1/health` (also mounted at `/health`)
  Returns service status, version, and timestamp.
- **Readiness Probe**: `GET /api/v1/health/ready` (also mounted at `/health/ready`)
  Inspects SQLite database connectivity (`SELECT 1`), local media storage accessibility, and FFmpeg binary resolution without external AI calls.

---

## 🧪 Comprehensive Test Suite

Run the full automated test suite (**135 passing tests covering Phases 1–14**):
```bash
pytest backend/tests/ -v
```

---

## ⚠️ Known Limitations & Scope Boundaries

- **Mock Provider Mode**: When `OPENAI_API_KEY` is not provided, the studio operates with built-in mock providers for transcription and comic generation to allow offline local development and automated testing.
- **Single-Node Local Storage**: Media files and SQLite records reside on the local filesystem. For distributed multi-node deployments, S3/GCS object storage and PostgreSQL can be configured.
- **Scope Boundaries**: Billing, subscriptions, social media auto-publishing, and user account authentication redesign are out of scope for the current phase.
