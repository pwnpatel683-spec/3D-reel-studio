"""
3D Reel Studio — Phase 17 Complete Production QA & Release Readiness Audit
Comprehensive verification suite testing API inventory, authentication, authorization matrix,
IDOR enumeration defense, media security, FFmpeg security, input validation, and end-to-end rendering.
"""

import io
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.migrations import run_migrations
from app.db.session import SessionLocal, init_db
from app.main import app
from app.models.project import (
    ComicFrame,
    ComicGeneration,
    ConsistentComicFrame,
    DetectedSubject,
    FaceDetection,
    LyricAnimation,
    LyricSegment,
    LyricStyle,
    MediaFile,
    PoseDetection,
    Project,
    RenderJob,
    SceneKeyframe,
    SegmentationResult,
    Transcript,
    TranscriptSegment,
    TransformationJob,
    VideoAnalysis,
    VideoScene,
    VisionAnalysis,
    generate_uuid,
)
from app.models.user import User, generate_user_id
from app.services.audio import extract_audio_from_video, resolve_ffmpeg_path
from app.services.maintenance import (
    audit_project_storage,
    cleanup_project_storage,
    reconcile_stale_jobs_on_startup,
)
from app.services.render import resize_and_fit_916, run_final_reel_render_sync
from app.services.storage import get_base_storage_dir, get_project_storage_dir


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Clears in-memory rate limits between tests."""
    limiter._records.clear()
    yield
    limiter._records.clear()


@pytest.fixture(scope="module")
def db_session():
    """Database session for audit assertions."""
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_client():
    """Fresh TestClient for API probing."""
    return TestClient(app)


@pytest.fixture
def two_audit_users(test_client: TestClient):
    """Creates two distinct isolated user accounts with valid JWT authorization headers."""
    email_a = f"audit_a_{generate_uuid()[:8]}@reelstudio.local"
    email_b = f"audit_b_{generate_uuid()[:8]}@reelstudio.local"

    res_a = test_client.post("/api/v1/auth/register", json={"email": email_a, "password": "PasswordA123!"}).json()
    res_b = test_client.post("/api/v1/auth/register", json={"email": email_b, "password": "PasswordB123!"}).json()

    return {
        "user_a": res_a["user"],
        "user_b": res_b["user"],
        "token_a": res_a["access_token"],
        "token_b": res_b["access_token"],
        "headers_a": {"Authorization": f"Bearer {res_a['access_token']}"},
        "headers_b": {"Authorization": f"Bearer {res_b['access_token']}"},
    }


# =============================================================================
# 1. FULL API INVENTORY & AUTHENTICATION AUDIT
# =============================================================================

def test_api_inventory_security_classification():
    """
    Audits all registered routes on the FastAPI application:
    Ensures that all project-scoped routes require authentication and that
    public routes are strictly restricted to health, docs, and authentication endpoints.
    """
    allowed_public_paths = {
        "/",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
        "/health",
        "/health/live",
        "/health/ready",
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
    }

    openapi_paths = app.openapi().get("paths", {})
    protected_route_count = 0
    public_route_count = 0

    for path in openapi_paths.keys():
        if path in allowed_public_paths:
            public_route_count += 1
        elif path.startswith("/api/v1/projects") or path.startswith("/api/v1/auth/me") or path.startswith("/api/v1/auth/logout"):
            protected_route_count += 1
        else:
            # Any unclassified route must not be accidentally exposed
            assert False, f"Unclassified route found in API: {path}"

    assert protected_route_count >= 25, f"Expected >= 25 protected routes, found {protected_route_count}"
    assert public_route_count >= 7


def test_unauthenticated_requests_strictly_rejected(test_client: TestClient):
    """
    Verifies that calling any protected endpoint without an Authorization header returns 401 UNAUTHORIZED.
    """
    # 1. List projects
    res1 = test_client.get("/api/v1/projects")
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Create project
    res2 = test_client.post("/api/v1/projects", json={"name": "Hacked"})
    assert res2.status_code == 401

    # 3. Project detail
    res3 = test_client.get("/api/v1/projects/PROJ-FAKE-123")
    assert res3.status_code == 401

    # 4. Current user
    res4 = test_client.get("/api/v1/auth/me")
    assert res4.status_code == 401

    # 5. Logout
    res5 = test_client.post("/api/v1/auth/logout")
    assert res5.status_code == 401


# =============================================================================
# 2. MULTI-USER IDOR & AUTHORIZATION MATRIX AUDIT
# =============================================================================

def test_complete_multi_user_authorization_matrix(test_client: TestClient, two_audit_users: dict):
    """
    Executes the complete multi-user security authorization matrix across every major pipeline resource:
    User A owns Project A; User B owns Project B.
    Verify that User A accessing Project B (or nested assets) returns 404 NOT_FOUND without leaking existence.
    """
    headers_a = two_audit_users["headers_a"]
    headers_b = two_audit_users["headers_b"]

    # 1. Create Project A and Project B
    proj_a = test_client.post("/api/v1/projects", json={"name": "Audit Project A"}, headers=headers_a).json()["project"]["id"]
    proj_b = test_client.post("/api/v1/projects", json={"name": "Audit Project B"}, headers=headers_b).json()["project"]["id"]

    # 2. Upload media to Project A and Project B
    dummy_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 512
    up_a = test_client.post(
        f"/api/v1/projects/{proj_a}/media",
        files={"file": ("video_a.mp4", io.BytesIO(dummy_mp4), "video/mp4")},
        data={"media_type": "source_video"},
        headers=headers_a,
    ).json()["media"]["id"]

    up_b = test_client.post(
        f"/api/v1/projects/{proj_b}/media",
        files={"file": ("video_b.mp4", io.BytesIO(dummy_mp4), "video/mp4")},
        data={"media_type": "source_video"},
        headers=headers_b,
    ).json()["media"]["id"]

    # --- MATRIX TEST: GET PROJECT ---
    assert test_client.get(f"/api/v1/projects/{proj_a}", headers=headers_a).status_code == 200  # A -> A
    assert test_client.get(f"/api/v1/projects/{proj_b}", headers=headers_b).status_code == 200  # B -> B
    assert test_client.get(f"/api/v1/projects/{proj_b}", headers=headers_a).status_code == 404  # A -> B (IDOR Blocked)
    assert test_client.get(f"/api/v1/projects/{proj_a}", headers=headers_b).status_code == 404  # B -> A (IDOR Blocked)

    # --- MATRIX TEST: PATCH PROJECT ---
    assert test_client.patch(f"/api/v1/projects/{proj_a}", json={"name": "A Renamed"}, headers=headers_a).status_code == 200
    assert test_client.patch(f"/api/v1/projects/{proj_b}", json={"name": "B Attacked"}, headers=headers_a).status_code == 404

    # --- MATRIX TEST: MEDIA DOWNLOAD & STREAMING ---
    assert test_client.get(f"/api/v1/projects/{proj_a}/media/{up_a}/download", headers=headers_a).status_code == 200
    assert test_client.get(f"/api/v1/projects/{proj_b}/media/{up_b}/download", headers=headers_a).status_code == 404
    assert test_client.get(f"/api/v1/projects/{proj_a}/media/{up_a}/file", headers=headers_b).status_code == 404

    # --- MATRIX TEST: AUDIO EXTRACTION ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/media/{up_b}/extract-audio", headers=headers_a).status_code == 404

    # --- MATRIX TEST: TRANSCRIPTION ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/media/{up_b}/transcribe", headers=headers_a).status_code == 404

    # --- MATRIX TEST: SCENE & VISION ANALYSIS ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/media/{up_b}/analyze", headers=headers_a).status_code == 404
    assert test_client.post(f"/api/v1/projects/{proj_b}/media/{up_b}/vision-analysis", headers=headers_a).status_code == 404

    # --- MATRIX TEST: 3D COMIC GENERATION ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/comic-generation", json={}, headers=headers_a).status_code == 404

    # --- MATRIX TEST: CHARACTER CONSISTENCY ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/consistency/profile", headers=headers_a).status_code == 404
    assert test_client.post(f"/api/v1/projects/{proj_b}/consistency/generate", json={}, headers=headers_a).status_code == 404

    # --- MATRIX TEST: SEGMENTATION ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/segmentation", json={}, headers=headers_a).status_code == 404

    # --- MATRIX TEST: LYRICS ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/lyrics/sync", json={}, headers=headers_a).status_code == 404
    assert test_client.get(f"/api/v1/projects/{proj_b}/lyrics", headers=headers_a).status_code == 404
    assert test_client.post(f"/api/v1/projects/{proj_b}/lyrics/preview", json={}, headers=headers_a).status_code == 404
    assert test_client.patch(f"/api/v1/projects/{proj_b}/lyrics/segments/SEG-123", json={}, headers=headers_a).status_code == 404

    # --- MATRIX TEST: RENDERING ---
    assert test_client.post(f"/api/v1/projects/{proj_b}/render", json={}, headers=headers_a).status_code == 404
    assert test_client.get(f"/api/v1/projects/{proj_b}/render", headers=headers_a).status_code == 404
    assert test_client.get(f"/api/v1/projects/{proj_b}/render/RND-123", headers=headers_a).status_code == 404
    assert test_client.post(f"/api/v1/projects/{proj_b}/render/RND-123/cancel", headers=headers_a).status_code == 404

    # --- MATRIX TEST: STORAGE AUDIT & CLEANUP ---
    assert test_client.get(f"/api/v1/projects/{proj_b}/storage-audit", headers=headers_a).status_code == 404
    assert test_client.post(f"/api/v1/projects/{proj_b}/storage-cleanup", json={}, headers=headers_a).status_code == 404


# =============================================================================
# 3. PATH TRAVERSAL & MEDIA SECURITY AUDIT
# =============================================================================

def test_path_traversal_and_filename_security(test_client: TestClient, two_audit_users: dict):
    """
    Verifies that directory traversal payloads, absolute paths, and encoded attacks in route IDs are rejected.
    """
    headers = two_audit_users["headers_a"]
    attack_payloads = [
        "../etc/passwd",
        "..\\windows\\system32",
        "....//....//etc/shadow",
        "%2e%2e%2fsecret",
        "/absolute/path/file",
        "C:\\Windows\\System32\\cmd.exe",
        ".hidden_file",
    ]

    for payload in attack_payloads:
        res1 = test_client.get(f"/api/v1/projects/{payload}", headers=headers)
        assert res1.status_code in (400, 404), f"Failed for payload: {payload}"

        res2 = test_client.get(f"/api/v1/projects/{payload}/storage-audit", headers=headers)
        assert res2.status_code in (400, 404)


# =============================================================================
# 4. FFMPEG SECURITY & SHELL INJECTION AUDIT
# =============================================================================

def test_ffmpeg_invocation_shell_injection_defense():
    """
    Verifies that shell metacharacters in filenames cannot cause arbitrary command execution.
    FFmpeg arguments are passed strictly as list arrays without shell=True.
    """
    dangerous_filenames = [
        "test; reboot.mp4",
        "clip $(whoami).mp4",
        "sample && calc.exe.mp4",
        "file`id`.mp4",
        "single_quote'test.mp4",
        "percent%temp%test.mp4",
        "caret^echo^danger.mp4",
    ]

    for fname in dangerous_filenames:
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = Path(tmpdir) / fname
            src_path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
            dst_path = Path(tmpdir) / "output.mp3"

            ffmpeg_bin = resolve_ffmpeg_path()
            if not ffmpeg_bin:
                pytest.skip("FFmpeg not installed in test environment")

            # Must run safely without throwing shell parsing exceptions
            try:
                extract_audio_from_video(src_path, dst_path)
            except Exception as e:
                # May fail on invalid video container or missing audio, but must never execute shell commands
                assert "reboot" not in str(e)
                assert "calc.exe" not in str(e)



# =============================================================================
# 5. INPUT VALIDATION & BOUNDARY TESTING
# =============================================================================

def test_input_validation_boundaries(test_client: TestClient, two_audit_users: dict):
    """
    Verifies that out-of-bounds, empty, or malicious parameter inputs are rejected with 422 Unprocessable Entity.
    """
    headers = two_audit_users["headers_a"]
    proj_id = test_client.post("/api/v1/projects", json={"name": "Boundary Test Proj"}, headers=headers).json()["project"]["id"]

    # 1. Project Creation with empty / whitespace name
    res_empty = test_client.post("/api/v1/projects", json={"name": "   "}, headers=headers)
    assert res_empty.status_code == 422

    # 2. Patch project with invalid status enum
    res_bad_status = test_client.patch(f"/api/v1/projects/{proj_id}", json={"status": "DESTROYED"}, headers=headers)
    assert res_bad_status.status_code == 422

    # 3. Lyric Segment update with out-of-range opacity (> 1.0 or < 0.0)
    res_bad_opacity = test_client.patch(
        f"/api/v1/projects/{proj_id}/lyrics/segments/SEG-123",
        json={"opacity": 5.0},
        headers=headers,
    )
    assert res_bad_opacity.status_code in (404, 422)

    # 4. Render request with invalid video codec
    res_bad_codec = test_client.post(
        f"/api/v1/projects/{proj_id}/render",
        json={"video_codec": "invalid_codec_xxx"},
        headers=headers,
    )
    assert res_bad_codec.status_code in (400, 422)


# =============================================================================
# 6. JOB LIFECYCLE & STARTUP RECONCILIATION AUDIT
# =============================================================================

def test_job_lifecycle_stale_reconciliation_audit(db_session: Session, two_audit_users: dict):
    """
    Verifies that orphaned in-flight jobs are safely transitioned to failed upon server restart.
    """
    user_id = two_audit_users["user_a"]["id"]
    proj_id = f"PROJ-STALE-{uuid.uuid4().hex[:8]}"

    proj = Project(id=proj_id, name="Stale Job Test", user_id=user_id)
    db_session.add(proj)

    active_render = RenderJob(
        id=f"rj-active-{uuid.uuid4().hex[:8]}",
        project_id=proj_id,
        status="processing",
        width=1080,
        height=1920,
        fps=30.0,
        video_codec="libx264",
        audio_codec="aac",
    )
    db_session.add(active_render)
    db_session.commit()

    # Run startup reconciliation
    counts = reconcile_stale_jobs_on_startup(db_session)
    assert counts["render_jobs"] >= 1

    db_session.refresh(active_render)
    assert active_render.status == "failed"
    assert active_render.error_code == "SERVER_RESTARTED_RECOVERY"


# =============================================================================
# 7. END-TO-END WORKFLOW & 9:16 MP4 FINAL VIDEO VALIDATION
# =============================================================================

def test_end_to_end_pipeline_and_mp4_validation(test_client: TestClient, two_audit_users: dict):
    """
    Executes a complete real-world Release Candidate workflow on a deterministic synthetic video:
    Upload -> Audio Extract -> Transcribe -> Scene Analysis -> Vision -> Comic Gen -> Consistency
    -> Segmentation -> Lyrics -> Final Render -> 9:16 H.264/AAC MP4 Validation.
    """
    headers = two_audit_users["headers_a"]
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        pytest.skip("FFmpeg required for end-to-end video synthesis")

    # 1. Create project
    res_proj = test_client.post("/api/v1/projects", json={"name": "RC End-to-End Test"}, headers=headers)
    assert res_proj.status_code == 201
    project_id = res_proj.json()["project"]["id"]

    # 2. Synthesize small 1-second 360x640 test MP4 video with test audio
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid_path = Path(tmp_vid.name)

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "color=c=navy:s=360x640:d=1",
        "-f", "lavfi", "-i", "sine=f=440:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(tmp_vid_path),
    ]
    proc = subprocess.run(cmd, capture_output=True)
    assert proc.returncode == 0, f"FFmpeg test video synthesis failed: {proc.stderr.decode('utf-8', errors='replace')}"

    try:
        # 3. Upload video
        with open(tmp_vid_path, "rb") as f:
            res_up = test_client.post(
                f"/api/v1/projects/{project_id}/media",
                files={"file": ("rc_test.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
                headers=headers,
            )
        assert res_up.status_code == 201
        source_media_id = res_up.json()["media"]["id"]

        # 4. Extract audio
        res_audio = test_client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/extract-audio", headers=headers)
        assert res_audio.status_code in (200, 201)
        audio_media_id = res_audio.json()["media"]["id"]

        # 5. Transcribe audio with mocked client
        class MockSegment:
            def __init__(self):
                self.id = 0
                self.seek = 0
                self.start = 0.0
                self.end = 1.0
                self.text = "Release Candidate Verified"
                self.tokens = []
                self.temperature = 0.0
                self.avg_logprob = -0.1
                self.compression_ratio = 1.1
                self.no_speech_prob = 0.01
                self.words = []

        class MockTranscript:
            def __init__(self):
                self.text = "Release Candidate Verified"
                self.language = "english"
                self.duration = 1.0
                self.segments = [MockSegment()]
                self.words = []

        mock_openai = MagicMock()
        mock_openai.audio.transcriptions.create.return_value = MockTranscript()

        with patch("app.services.transcription.OpenAI", return_value=mock_openai), \
             patch("app.services.transcription.settings.OPENAI_API_KEY", "sk-mock-key"):
            res_trans = test_client.post(f"/api/v1/projects/{project_id}/media/{audio_media_id}/transcribe", headers=headers)
        assert res_trans.status_code in (200, 201)

        # 6. Scene Analysis
        res_scene = test_client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/analyze", headers=headers)
        assert res_scene.status_code in (200, 201)

        # 7. Vision Analysis
        res_vision = test_client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/vision-analysis", headers=headers)
        assert res_vision.status_code in (200, 201)

        # 8. Comic & Consistency Generation (Mock Mode)
        with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
            res_comic = test_client.post(
                f"/api/v1/projects/{project_id}/comic-generation",
                json={"provider": "mock", "style_preset": "cyberpunk_3d"},
                headers=headers,
            )
            assert res_comic.status_code in (200, 201)

            res_const = test_client.post(
                f"/api/v1/projects/{project_id}/consistency/generate",
                json={"style_preset": "cyberpunk_3d"},
                headers=headers,
            )
            assert res_const.status_code in (200, 201)

        # 9. Segmentation
        res_seg = test_client.post(
            f"/api/v1/projects/{project_id}/segmentation",
            json={"background_mode": "ORIGINAL"},
            headers=headers,
        )
        assert res_seg.status_code in (200, 201)

        # 10. Lyrics Sync
        res_lyr = test_client.post(f"/api/v1/projects/{project_id}/lyrics/sync", json={"force_recreate": True}, headers=headers)
        assert res_lyr.status_code in (200, 201)

        # 11. Final 9:16 Reel Render
        res_render = test_client.post(
            f"/api/v1/projects/{project_id}/render",
            json={"force_rerender": True, "output_width": 1080, "output_height": 1920, "fps": 30.0},
            headers=headers,
        )
        assert res_render.status_code in (200, 201)
        render_job = res_render.json()["job"]
        assert render_job["status"] == "completed"
        output_media_id = render_job["output_media_file_id"]

        # 12. Final MP4 Binary & Metadata Validation
        res_dl = test_client.get(f"/api/v1/projects/{project_id}/media/{output_media_id}/download", headers=headers)
        assert res_dl.status_code == 200
        assert len(res_dl.content) > 1000
        assert res_dl.headers.get("content-type") in ("video/mp4", "application/octet-stream")

        # Probe MP4 streams with FFprobe / FFmpeg
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as out_mp4:
            out_mp4_path = Path(out_mp4.name)
            out_mp4_path.write_bytes(res_dl.content)

        try:
            probe_cmd = [
                ffmpeg_bin, "-i", str(out_mp4_path)
            ]
            probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
            output_info = probe_res.stderr

            # Verify Container & Resolution
            assert "Video: h264" in output_info or "Video: libx264" in output_info
            assert "1080x1920" in output_info
            assert "Audio: aac" in output_info
        finally:
            if out_mp4_path.exists():
                out_mp4_path.unlink(missing_ok=True)

    finally:
        if tmp_vid_path.exists():
            tmp_vid_path.unlink(missing_ok=True)
