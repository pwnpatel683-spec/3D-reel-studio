# ◈ 3D REEL STUDIO — Backend API (FastAPI, SQLite, FFmpeg, OpenCV & OpenAI)

FastAPI backend service for **3D Reel Studio**, providing API routing, SQLite database persistence with SQLAlchemy, secure multipart media upload, FFmpeg audio extraction, OpenAI Whisper audio transcription, video stream metadata extraction, shot/scene boundary detection, visual keyframe extraction, face detection & landmark localization, primary subject tracking, face reference frame filtering, 17-point body pose estimation, reference-guided character consistency profile management, sequential temporal frame chaining, non-identifying visual diagnostics, subject-guided GrabCut foreground segmentation, clean background inpainting, dynamic background adaptation modes, health monitoring, standardized responses, and CORS integration for the AI video transformation platform.

> **PHASE 11 SCOPE**: This service provides the core application architecture, API v1 routing, SQLite database persistence (`Project`, `MediaFile`, `TransformationJob`, `Transcript`, `TranscriptSegment`, `VideoAnalysis`, `VideoScene`, `SceneKeyframe`, `VisionAnalysis`, `DetectedSubject`, `FaceDetection`, `FaceReference`, `PoseDetection`, `PoseLandmark`, `ComicGeneration`, `ComicFrame`, `CharacterConsistencyProfile`, `ConsistencyGeneration`, `ConsistentComicFrame`, `SegmentationResult` models), secure media storage (`source/`, `face-reference/`, `audio/`, `keyframes/`, `comic-frames/`, `consistent-frames/`, `segmentation/`), FFmpeg audio extraction pipeline, OpenAI Whisper audio transcription, FFmpeg video scene & content analysis, Computer Vision Face Detection & Pose Tracking, 3D Comic Style Generation, Reference-Guided Identity + Temporal Consistency Engine, and Foreground Segmentation + Dynamic Background Layering (`POST /api/v1/projects/{project_id}/segmentation`).

---

## 📋 Requirements & System Dependencies

- **Python**: 3.11+
- **FastAPI**: 0.115+
- **Uvicorn**: 0.30+
- **SQLAlchemy**: 2.0+
- **Pydantic**: 2.7+
- **OpenAI**: 1.0+ (Official SDK)
- **OpenCV**: 4.10+ / 5.0+ (Headless)
- **Pillow & NumPy**: Image manipulation and tensor computation
- **FFmpeg & FFprobe**: System executable (required for audio extraction and video scene analysis)

---

## 🔑 Environment & Provider Setup (Phase 6, 9, 10 & 11)

Set your configuration in `backend/.env`:
```env
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_TRANSCRIPTION_MODEL=whisper-1
COMIC_GENERATION_PROVIDER=mock   # or "openai" for DALL-E 3
COMIC_GENERATION_MODEL=dall-e-3
SEGMENTATION_PROVIDER=opencv_guided    # or "mock"
SEGMENTATION_MODEL=grabcut_pose_prior
SEGMENTATION_DEFAULT_BG_MODE=ORIGINAL # ORIGINAL | SOFT_BLUR | DEPTH_STYLE | COMIC_STYLE
```

> **SECURITY**: `OPENAI_API_KEY` and all internal provider settings are strictly managed backend-side and never exposed to the frontend.

---

## 🛠️ FFmpeg & FFprobe Setup

### 1. Installation
- **Windows**: `winget install Gyan.FFmpeg.Essentials`
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 2. Verify Installation
```bash
ffmpeg -version
ffprobe -version
```

---

## 🚀 Setup & Installation

### 1. Create and Activate Virtual Environment

```bash
cd backend
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Backend Server

```bash
uvicorn app.main:app --reload --port 8000
```

---

## 🌐 API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Root service status and API docs link |
| `GET` | `/api/v1/health` | Service health status |
| `GET` | `/api/v1/health/ready` | Service readiness probe |
| `POST` | `/api/v1/projects` | Create a new studio project session |
| `GET` | `/api/v1/projects` | List all studio projects |
| `GET` | `/api/v1/projects/{project_id}` | Retrieve project detail with media, transcripts, video analyses, vision analyses, comic generations, consistency profiles, and segmentation results |
| `PATCH` | `/api/v1/projects/{project_id}` | Update project name or status |
| `POST` | `/api/v1/projects/{project_id}/media` | Upload source video or face reference |
| `GET` | `/api/v1/projects/{project_id}/media/{media_id}/file` | Retrieve/stream binary media file (video, audio, keyframe, face ref, comic frame, consistent frame, mask, foreground, background, composite) |
| `POST` | `/api/v1/projects/{project_id}/media/{media_id}/extract-audio` | Extract MP3 audio from source video via FFmpeg |
| `POST` | `/api/v1/projects/{project_id}/media/{media_id}/transcribe` | Transcribe extracted audio via OpenAI Whisper API |
| `POST` | `/api/v1/projects/{project_id}/media/{media_id}/analyze` | Analyze video stream metadata, detect scene shots, and extract keyframes |
| `POST` | `/api/v1/projects/{project_id}/media/{media_id}/vision-analysis` | Extract face bounding boxes & landmarks, rank primary subject, filter face references, estimate 17-pt body pose |
| `POST` | `/api/v1/projects/{project_id}/comic-generation` | Generate 9:16 3D comic frames for a scene or batch of scenes |
| `POST` | `/api/v1/projects/{project_id}/consistency/profile` | Build or fetch project-local Character Consistency Profile |
| `POST` | `/api/v1/projects/{project_id}/consistency/generate` | Generate reference-guided, temporally chained 3D comic frames with style locking |
| `POST` | `/api/v1/projects/{project_id}/segmentation` | Segment foreground character from consistent comic frames, inpaint background, apply adaptive style modes, and generate independent layer assets |
| `POST` | `/api/v1/projects/{project_id}/lyrics/sync` | Synchronize Phase 6 Whisper transcript segments into editable kinetic lyric segments |
| `GET` | `/api/v1/projects/{project_id}/lyrics` | Retrieve project lyric segments, styles, animations, and preview history |
| `PATCH` | `/api/v1/projects/{project_id}/lyrics/segments/{segment_id}` | Update text, typography style, animation, scale, opacity, and positioning of a lyric segment |
| `POST` | `/api/v1/projects/{project_id}/lyrics/preview` | Render Text-Behind-Character multi-layer composite preview frame for a timestamp/segment |

---

## ⚡ Example Kinetic Lyrics Preview API Request

```bash
POST /api/v1/projects/PROJ-A1B2C3D4/lyrics/preview
Content-Type: application/json
{
  "timestamp": 1.5,
  "lyric_segment_id": "seg-uuid-1",
  "position_y": 0.75,
  "position_x": 0.5,
  "scale": 1.0,
  "opacity": 1.0
}
```

Response:
```json
{
  "success": true,
  "preview": {
    "id": "preview-uuid-1",
    "project_id": "PROJ-A1B2C3D4",
    "lyric_segment_id": "seg-uuid-1",
    "timestamp": 1.5,
    "output_media_file_id": "MEDIA-PREVIEW-1",
    "text_rendered": "Hello everyone",
    "style_name": "Bold Cinematic",
    "animation_type": "POP",
    "position_x": 0.5,
    "position_y": 0.75,
    "scale": 1.0,
    "opacity": 1.0
  }
}
```

---

## 🧪 Running Automated Tests

Run the full comprehensive test suite (**113 passing tests across Phase 1–12**):

```bash
pytest backend/tests/ -v
```

> **IMPORTANT SCOPE NOTE**: Phase 12 focuses exclusively on kinetic typography layout, motion calculation, soft alpha occlusion behind the character, and timestamp preview generation. Final FFmpeg MP4 encoding, audio remuxing, and video export are scheduled for the next phase.

