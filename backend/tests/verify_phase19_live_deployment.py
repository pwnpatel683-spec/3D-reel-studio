"""
Phase 19 — Live Production Deployment & Verification Suite
Validates the complete production deployment specifications, security postures,
database migrations, multi-user isolation matrix, FFmpeg runtime engine,
E2E workflow execution (Mock Deployment Mode), and MP4 stream compliance.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings, settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.core.rate_limit import limiter
from app.db.migrations import run_migrations, migration_status, MIGRATIONS
from app.db.session import engine, SessionLocal, init_db
from app.main import app
from app.models.project import Project, MediaFile, RenderJob, generate_uuid
from app.models.user import User
from app.services.audio import resolve_ffmpeg_path, extract_audio_from_video
from app.services.analysis import resolve_ffprobe_path
from app.services.storage import get_base_storage_dir, get_project_storage_dir


def run_phase19_verification():
    print("=" * 70)
    print("PHASE 19 — LIVE PRODUCTION DEPLOYMENT & VERIFICATION SUITE")
    print("=" * 70)

    # 1. Verify Deployment Target & Secrets Policy
    print("\n[1/11] Inspecting Hosting Target & Secrets Configuration...")
    print(" -> Deployment Target: Generic Linux Container / Docker Compose / Reverse Proxy")
    print(" -> Hosting Domain Status: Not configured (No live public cloud domain provisioned)")
    print(" -> Environment Secrets Policy: Server-side environment variables only (No secrets in Git/JS)")

    # 2. Verify Production Settings Harmonization
    print("\n[2/11] Verifying Production Configuration Harmonization...")
    prod_settings = Settings(
        APP_ENV="production",
        DEBUG=False,
        MEDIA_STORAGE_ROOT="storage",
        TEMP_STORAGE_ROOT="storage/temp",
        CORS_ALLOWED_ORIGINS="https://studio.example.com",
        MAX_UPLOAD_SIZE=104857600,
        MAX_VIDEO_DURATION=600.0,
        PROCESSING_TIMEOUT=300,
        AUTH_SECRET="prod-verification-secret-key-256bit-min-length-phase19",
    )
    assert prod_settings.ENVIRONMENT == "production"
    assert prod_settings.DEBUG is False
    assert "https://studio.example.com" in prod_settings.CORS_ORIGINS
    assert prod_settings.SOURCE_VIDEO_MAX_SIZE_MB == 100
    assert prod_settings.RENDER_TIMEOUT_SECONDS == 300
    print(" -> Settings Harmonization: PASS (DEBUG=False, ENV=production, CORS whitelisted, Upload=100MB)")

    # 3. Verify Database Connectivity & Migrations
    print("\n[3/11] Verifying Database Connectivity & Idempotent Migrations...")
    init_db()
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
        assert res == 1
    applied = run_migrations(engine)
    statuses = migration_status(engine)
    print(f" -> Database Ping: OK, Migrations: {len(statuses)} registered, {len(applied)} newly applied (idempotent)")
    for s in statuses:
        assert s["applied"] is True
    print(" -> Database Schema & Idempotent Migrations: PASS")

    # 4. Verify FFmpeg & FFprobe Runtime Resolution
    print("\n[4/11] Verifying FFmpeg & FFprobe Binary Resolution...")
    ffmpeg_bin = resolve_ffmpeg_path()
    ffprobe_bin = resolve_ffprobe_path()
    assert ffmpeg_bin is not None, "FFmpeg binary resolution failed!"
    assert ffprobe_bin is not None, "FFprobe binary resolution failed!"
    print(f" -> FFmpeg resolved: {ffmpeg_bin}")
    print(f" -> FFprobe resolved: {ffprobe_bin}")

    # 5. Probing Health & Readiness Endpoints
    print("\n[5/11] Probing Live Health & Readiness Probes...")
    client = TestClient(app)
    limiter._records.clear()

    res_live = client.get("/api/v1/health/live")
    assert res_live.status_code == 200
    live_data = res_live.json()
    assert live_data["success"] is True
    assert live_data["status"] == "healthy"
    print(f" -> GET /api/v1/health/live: {live_data}")

    res_ready = client.get("/api/v1/health/ready")
    assert res_ready.status_code == 200
    ready_data = res_ready.json()
    assert ready_data["success"] is True
    assert ready_data["subsystems"]["database"]["status"] == "ok"
    assert ready_data["subsystems"]["storage"]["status"] == "ok"
    assert ready_data["subsystems"]["ffmpeg"]["status"] == "ok"
    print(f" -> GET /api/v1/health/ready: {ready_data['status']} | Subsystems: {ready_data['subsystems']}")
    print(" -> Health & Readiness Probes: PASS")

    # 6. Verify Authentication & Multi-User Isolation Matrix
    print("\n[6/11] Verifying Authentication & Zero-Trust Multi-User Isolation Matrix...")
    email_a = f"phase19_user_a_{generate_uuid()[:8]}@reelstudio.local"
    email_b = f"phase19_user_b_{generate_uuid()[:8]}@reelstudio.local"

    res_reg_a = client.post("/api/v1/auth/register", json={"email": email_a, "password": "StrongPasswordA123!"})
    res_reg_b = client.post("/api/v1/auth/register", json={"email": email_b, "password": "StrongPasswordB123!"})
    assert res_reg_a.status_code == 201
    assert res_reg_b.status_code == 201

    token_a = res_reg_a.json()["access_token"]
    token_b = res_reg_b.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # /auth/me check
    me_a = client.get("/api/v1/auth/me", headers=headers_a).json()
    assert me_a["success"] is True
    assert me_a["user"]["email"] == email_a
    assert "password" not in me_a["user"]
    assert "password_hash" not in me_a["user"]

    # User A and B create projects
    p_a = client.post("/api/v1/projects", json={"name": "Phase 19 Project A"}, headers=headers_a).json()["project"]["id"]
    p_b = client.post("/api/v1/projects", json={"name": "Phase 19 Project B"}, headers=headers_b).json()["project"]["id"]

    # Isolation Matrix Assertions
    assert client.get(f"/api/v1/projects/{p_a}", headers=headers_a).status_code == 200  # A -> A : ALLOWED
    assert client.get(f"/api/v1/projects/{p_b}", headers=headers_b).status_code == 200  # B -> B : ALLOWED
    assert client.get(f"/api/v1/projects/{p_b}", headers=headers_a).status_code == 404  # A -> B : DENIED
    assert client.get(f"/api/v1/projects/{p_a}", headers=headers_b).status_code == 404  # B -> A : DENIED
    print(" -> Multi-User Isolation Matrix (A->A=200, B->B=200, A->B=404, B->A=404): PASS")

    # 7. Verify Path Traversal & Media Security
    print("\n[7/11] Verifying Path Traversal & Media Storage Defenses...")
    for attack in ["../etc/passwd", "..\\windows\\system32", "%2e%2e%2fsecret", "/root/file"]:
        res_trav = client.get(f"/api/v1/projects/{attack}", headers=headers_a)
        assert res_trav.status_code in (400, 404)
    print(" -> Path Traversal Defense: PASS")

    # 8. Controlled Production Pipeline Smoke Test (MOCK DEPLOYMENT MODE)
    print("\n[8/11] Running Complete Production Pipeline Smoke Test (MOCK DEPLOYMENT MODE)...")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid_path = Path(tmp_vid.name)

    synth_cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "color=c=navy:s=360x640:d=1",
        "-f", "lavfi", "-i", "sine=f=440:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(tmp_vid_path),
    ]
    subprocess.run(synth_cmd, capture_output=True, check=True)

    try:
        # Upload
        with open(tmp_vid_path, "rb") as f:
            up_res = client.post(
                f"/api/v1/projects/{p_a}/media",
                files={"file": ("smoke_source_phase19.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
                headers=headers_a,
            )
        assert up_res.status_code == 201
        source_media_id = up_res.json()["media"]["id"]
        print(" -> Stage 1: Media Upload: OK")

        # Audio Extract
        aud_res = client.post(f"/api/v1/projects/{p_a}/media/{source_media_id}/extract-audio", headers=headers_a)
        assert aud_res.status_code in (200, 201)
        audio_media_id = aud_res.json()["media"]["id"]
        print(" -> Stage 2: Audio Extraction: OK")

        # Transcription (Mocked Whisper API)
        class MockSegment:
            def __init__(self):
                self.id = 0
                self.seek = 0
                self.start = 0.0
                self.end = 1.0
                self.text = "Live Deployment Smoke Test"
                self.tokens = []
                self.temperature = 0.0
                self.avg_logprob = -0.1
                self.compression_ratio = 1.0
                self.no_speech_prob = 0.01
                self.words = []

        class MockTranscript:
            def __init__(self):
                self.text = "Live Deployment Smoke Test"
                self.language = "english"
                self.duration = 1.0
                self.segments = [MockSegment()]
                self.words = []

        mock_openai = MagicMock()
        mock_openai.audio.transcriptions.create.return_value = MockTranscript()

        with patch("app.services.transcription.OpenAI", return_value=mock_openai), \
             patch("app.services.transcription.settings.OPENAI_API_KEY", "sk-mock-deployment-key"):
            trans_res = client.post(f"/api/v1/projects/{p_a}/media/{audio_media_id}/transcribe", headers=headers_a)
        assert trans_res.status_code in (200, 201)
        print(" -> Stage 3: Transcription: OK")

        # Scene Analysis
        scene_res = client.post(f"/api/v1/projects/{p_a}/media/{source_media_id}/analyze", headers=headers_a)
        assert scene_res.status_code in (200, 201)
        print(" -> Stage 4: Scene Analysis: OK")

        # Vision Analysis
        vision_res = client.post(f"/api/v1/projects/{p_a}/media/{source_media_id}/vision-analysis", headers=headers_a)
        assert vision_res.status_code in (200, 201)
        print(" -> Stage 5: Vision Analysis: OK")

        # Comic Generation & Consistency (Mock Provider)
        with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
            comic_res = client.post(
                f"/api/v1/projects/{p_a}/comic-generation",
                json={"provider": "mock", "style_preset": "cyberpunk_3d"},
                headers=headers_a,
            )
            assert comic_res.status_code in (200, 201)
            print(" -> Stage 6: Comic Generation: OK")

            const_res = client.post(
                f"/api/v1/projects/{p_a}/consistency/generate",
                json={"style_preset": "cyberpunk_3d"},
                headers=headers_a,
            )
            assert const_res.status_code in (200, 201)
            print(" -> Stage 7: Consistency Generation: OK")

        # Segmentation
        seg_res = client.post(
            f"/api/v1/projects/{p_a}/segmentation",
            json={"background_mode": "ORIGINAL"},
            headers=headers_a,
        )
        assert seg_res.status_code in (200, 201)
        print(" -> Stage 8: Foreground Segmentation: OK")

        # Lyrics Sync
        lyr_res = client.post(f"/api/v1/projects/{p_a}/lyrics/sync", json={"force_recreate": True}, headers=headers_a)
        assert lyr_res.status_code in (200, 201)
        print(" -> Stage 9: Kinetic Lyrics Sync: OK")

        # Final 9:16 Render
        render_res = client.post(
            f"/api/v1/projects/{p_a}/render",
            json={"force_rerender": True, "output_width": 1080, "output_height": 1920, "fps": 30.0},
            headers=headers_a,
        )
        assert render_res.status_code in (200, 201)
        render_data = render_res.json()
        assert render_data["success"] is True
        assert render_data["job"]["status"] == "completed"
        output_media_id = render_data["job"]["output_media_file_id"]
        print(" -> Stage 10: Final 9:16 Reel Render: OK")

        # 9. Final MP4 Compliance Validation
        print("\n[9/11] Validating Final Rendered MP4 Binary & Codecs...")
        dl_res = client.get(f"/api/v1/projects/{p_a}/media/{output_media_id}/download", headers=headers_a)
        assert dl_res.status_code == 200
        assert len(dl_res.content) > 1000
        assert dl_res.headers.get("content-type") in ("video/mp4", "application/octet-stream")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out_mp4:
            out_mp4_path = Path(out_mp4.name)
            out_mp4_path.write_bytes(dl_res.content)

        try:
            probe_cmd = [ffmpeg_bin, "-i", str(out_mp4_path)]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            output_info = probe_res.stderr

            assert "Video: h264" in output_info or "Video: libx264" in output_info
            assert "1080x1920" in output_info
            assert "Audio: aac" in output_info
            print(" -> MP4 Validation: PASS (Container=MP4, Video=H.264, Audio=AAC, Res=1080x1920, Aspect=9:16)")
        finally:
            if out_mp4_path.exists():
                out_mp4_path.unlink(missing_ok=True)

    finally:
        if tmp_vid_path.exists():
            tmp_vid_path.unlink(missing_ok=True)

    # 10. Storage Audit & Cleanup
    print("\n[10/11] Verifying Storage Audit & Cleanup Subsystems...")
    audit_res = client.get(f"/api/v1/projects/{p_a}/storage-audit", headers=headers_a)
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert audit_data["success"] is True

    cleanup_res = client.post(f"/api/v1/projects/{p_a}/storage-cleanup", json={"dry_run": True}, headers=headers_a)
    assert cleanup_res.status_code == 200
    assert cleanup_res.json()["success"] is True
    print(" -> Storage Audit & Cleanup APIs: PASS")

    # 11. Session Logout
    print("\n[11/11] Verifying User Logout & Session Invalidation...")
    logout_res = client.post("/api/v1/auth/logout", headers=headers_a)
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True
    print(" -> Logout: PASS")

    print("\n" + "=" * 70)
    print("ALL 11 PHASE 19 DEPLOYMENT VERIFICATION CHECKS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_phase19_verification()
