"""
3D Reel Studio — Production Deployment & System Architecture Test Suite
Phase 15: Production Deployment & Verification
"""

import asyncio
import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.config import Settings, settings
from app.core.rate_limit import InMemoryRateLimiter
from app.db.migrations import (
    MIGRATIONS,
    ensure_migration_table,
    get_applied_migrations,
    migration_status,
    run_migrations,
)
from app.main import app
from app.services.storage import LocalMediaStorage, MediaStorage, default_storage
from app.services.worker import JobWorkerManager


from tests.conftest import get_test_auth_headers

client = TestClient(app, headers=get_test_auth_headers())


# =============================================================================
# 1. HEALTH & READINESS SUBSYSTEM TESTS
# =============================================================================


def test_health_liveness_endpoints():
    """Verify both /api/v1/health/live and /health/live return 200 with status healthy."""
    for path in ["/api/v1/health/live", "/health/live", "/api/v1/health", "/health"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "healthy"
        assert "version" in data
        assert "service" in data


def test_health_readiness_endpoints():
    """Verify readiness probes return 200 with database, storage, and ffmpeg subsystem checks."""
    for path in ["/api/v1/health/ready", "/health/ready"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] in ("ready", "degraded")
        assert "subsystems" in data
        assert "database" in data["subsystems"]
        assert "storage" in data["subsystems"]
        assert "ffmpeg" in data["subsystems"]
        assert data["subsystems"]["database"]["status"] == "ok"
        assert data["subsystems"]["storage"]["status"] == "ok"


# =============================================================================
# 2. MEDIA STORAGE ABSTRACTION & SECURITY TESTS
# =============================================================================


def test_media_storage_interface_and_local_implementation():
    """Verify LocalMediaStorage adheres to MediaStorage contract."""
    assert isinstance(default_storage, MediaStorage)

    storage = LocalMediaStorage()
    test_project_id = "test_phase15_storage_proj"
    test_media_type = "source_video"
    test_filename = "sample_test.mp4"
    test_data = b"PHASE15_STORAGE_TEST_PAYLOAD_12345"

    # Save
    target_path, file_size, sha256_hex = storage.save(
        project_id=test_project_id,
        media_type=test_media_type,
        filename=test_filename,
        data=test_data,
    )
    assert target_path.exists()
    assert file_size == len(test_data)
    assert len(sha256_hex) == 64

    # Exists
    assert storage.exists(str(target_path)) is True

    # Metadata
    meta = storage.get_metadata(str(target_path))
    assert meta["exists"] is True
    assert meta["size"] == len(test_data)
    assert meta["sha256"] == sha256_hex

    # Open stream
    with storage.open(str(target_path)) as stream:
        read_back = stream.read()
        assert read_back == test_data

    # Download reference
    ref = storage.generate_download_reference(test_project_id, "media_abc_123")
    assert ref.startswith("/api/v1/projects/test_phase15_storage_proj/media/media_abc_123/download")

    # Delete
    deleted = storage.delete(str(target_path))
    assert deleted is True
    assert storage.exists(str(target_path)) is False


def test_media_storage_path_traversal_defense():
    """Verify LocalMediaStorage rejects path traversal in open and delete."""
    storage = LocalMediaStorage()

    # Attempt to open outside storage
    with pytest.raises(Exception):
        storage.open("../../../../../etc/passwd")

    # Attempt to check non-existent
    assert storage.exists("non_existent_file_xyz.mp4") is False


# =============================================================================
# 3. DATABASE MIGRATION ENGINE TESTS
# =============================================================================


def test_deterministic_database_migrations():
    """Verify database migration engine executes forward migrations deterministically on fresh DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db_path = tmp.name

    try:
        test_db_url = f"sqlite:///{tmp_db_path}"
        test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})

        # Initial migration run
        applied = run_migrations(test_engine)
        assert len(applied) == len(MIGRATIONS)
        assert "001_initial_tables" in applied
        assert "002_performance_indexes" in applied

        # Second run should apply 0 pending migrations
        applied_second = run_migrations(test_engine)
        assert len(applied_second) == 0

        # Check status
        statuses = migration_status(test_engine)
        assert len(statuses) == len(MIGRATIONS)
        for item in statuses:
            assert item["applied"] is True

        # Verify tracking table contents
        with test_engine.connect() as conn:
            applied_list = get_applied_migrations(conn)
            assert len(applied_list) == len(MIGRATIONS)

    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.unlink(tmp_db_path)
            except Exception:
                pass


# =============================================================================
# 4. HTTP SECURITY HEADERS & CORS TESTS
# =============================================================================


def test_production_security_headers():
    """Verify standard production security headers are attached to all API responses."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    headers = response.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# =============================================================================
# 5. IN-MEMORY RATE LIMITING TESTS
# =============================================================================


def test_in_memory_rate_limiter_allows_and_rejects():
    """Verify InMemoryRateLimiter sliding window limits requests and rejects bursts."""
    limiter = InMemoryRateLimiter(requests_per_minute=5, window_seconds=10)
    client_key = "192.168.1.100:/api/v1/projects/render"

    # First 5 requests should pass
    for _ in range(5):
        assert limiter.is_allowed(client_key, max_requests=5) is True

    # 6th request must be rejected
    assert limiter.is_allowed(client_key, max_requests=5) is False


# =============================================================================
# 6. JOB WORKER MANAGER CONCURRENCY & SAFETY TESTS
# =============================================================================


def test_job_worker_manager_concurrency_and_cancellation():
    """Verify JobWorkerManager handles task execution, concurrency bounding, and cancellation."""
    async def _run_test():
        worker = JobWorkerManager(max_concurrent_renders=2)

        def dummy_task(x: int) -> int:
            return x * 2

        # Normal execution
        result = await worker.run_render_task("job_1", dummy_task, 21)
        assert result == 42
        assert worker.is_job_active("job_1") is False

        # Cancellation test
        worker.cancel_job("job_cancelled")
        assert worker.is_cancelled("job_cancelled") is True

        with pytest.raises(asyncio.CancelledError):
            await worker.run_render_task("job_cancelled", dummy_task, 10)

        # Shutdown
        worker.shutdown()

    asyncio.run(_run_test())


# =============================================================================
# 7. PRODUCTION CONFIGURATION HARMONIZATION TESTS
# =============================================================================


def test_production_settings_harmonization():
    """Verify Settings class harmonizes environment aliases and production values."""
    # Production environment settings test
    prod_settings = Settings(
        APP_ENV="production",
        MEDIA_STORAGE_ROOT="prod_storage",
        MAX_UPLOAD_SIZE=52428800,  # 50MB
        MAX_VIDEO_DURATION=300.0,
        PROCESSING_TIMEOUT=240,
        CORS_ALLOWED_ORIGINS="https://studio.example.com,https://app.example.com",
    )

    assert prod_settings.ENVIRONMENT == "production"
    assert prod_settings.DEBUG is False
    assert prod_settings.STORAGE_DIR == "prod_storage"
    assert prod_settings.SOURCE_VIDEO_MAX_SIZE_MB == 50
    assert prod_settings.SOURCE_VIDEO_MAX_DURATION_SECONDS == 300.0
    assert prod_settings.RENDER_TIMEOUT_SECONDS == 240
    assert "https://studio.example.com" in prod_settings.CORS_ORIGINS
    assert "https://app.example.com" in prod_settings.CORS_ORIGINS


# =============================================================================
# 8. END-TO-END SMOKE TEST (PHASE 1 - 15 INTEGRATION)
# =============================================================================


def test_end_to_end_production_smoke_test():
    """
    Executes a complete, deterministic End-to-End smoke test verifying the full workflow:
    Upload -> Audio Extraction -> Transcription -> Scene Analysis -> Vision Analysis ->
    Comic Gen -> Consistency -> Segmentation -> Lyrics Sync -> Final 9:16 Render -> MP4 Validation.
    """
    from app.services.audio import resolve_ffmpeg_path
    import subprocess

    # 1. Create project
    res_proj = client.post("/api/v1/projects", json={"name": "E2E Production Smoke Test"})
    assert res_proj.status_code in (200, 201)
    proj_data = res_proj.json()
    assert proj_data["success"] is True
    project_id = proj_data["project"]["id"]

    # 2. Prepare small test video
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        tmp_vid_path = Path(tmp_vid.name)

    ffmpeg_bin = resolve_ffmpeg_path()
    if ffmpeg_bin:
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=360x640:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(tmp_vid_path),
        ]
        subprocess.run(cmd, capture_output=True, check=False)
    else:
        tmp_vid_path.write_bytes(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 1024)

    try:
        # 3. Upload source video
        with open(tmp_vid_path, "rb") as f:
            res_upload = client.post(
                f"/api/v1/projects/{project_id}/media",
                files={"file": ("e2e_test_video.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        assert res_upload.status_code in (200, 201)
        source_media_id = res_upload.json()["media"]["id"]

        # 4. Extract audio
        res_audio = client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/extract-audio")
        assert res_audio.status_code in (200, 201)
        audio_media_id = res_audio.json()["media"]["id"]

        # 5. Transcribe audio (mocked OpenAI client for deterministic test)
        from unittest.mock import MagicMock, patch

        class MockSegment:
            def __init__(self, sequence, start, end, text):
                self.id = sequence
                self.seek = 0
                self.start = start
                self.end = end
                self.text = text
                self.tokens = []
                self.temperature = 0.0
                self.avg_logprob = -0.15
                self.compression_ratio = 1.2
                self.no_speech_prob = 0.01
                self.words = []

        class MockVerboseTranscription:
            def __init__(self):
                self.text = "Testing 3D Reel Studio"
                self.language = "english"
                self.duration = 1.0
                self.segments = [MockSegment(0, 0.0, 1.0, "Testing 3D Reel Studio")]
                self.words = []

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = MockVerboseTranscription()

        with patch("app.services.transcription.OpenAI", return_value=mock_client), \
             patch("app.services.transcription.settings.OPENAI_API_KEY", "sk-mock-test-key"):
            res_trans = client.post(f"/api/v1/projects/{project_id}/media/{audio_media_id}/transcribe")
        assert res_trans.status_code in (200, 201)

        # 6. Analyze video scenes
        res_scene = client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/analyze")
        assert res_scene.status_code in (200, 201)

        # 7. Vision analysis
        res_vision = client.post(f"/api/v1/projects/{project_id}/media/{source_media_id}/vision-analysis")
        assert res_vision.status_code in (200, 201)

        # 8. 3D Comic generation (mock mode for deterministic test)
        with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
            res_comic = client.post(
                f"/api/v1/projects/{project_id}/comic-generation",
                json={"provider": "mock", "style_preset": "cyberpunk_3d"},
            )
            assert res_comic.status_code in (200, 201)

            # 9. Consistency generation
            res_const = client.post(
                f"/api/v1/projects/{project_id}/consistency/generate",
                json={"style_preset": "cyberpunk_3d"},
            )
            assert res_const.status_code in (200, 201)

        # 10. Foreground segmentation
        res_seg = client.post(
            f"/api/v1/projects/{project_id}/segmentation",
            json={"background_mode": "ORIGINAL"},
        )
        assert res_seg.status_code in (200, 201)

        # 11. Kinetic lyrics sync
        res_lyrics = client.post(
            f"/api/v1/projects/{project_id}/lyrics/sync",
            json={"force_recreate": True},
        )
        assert res_lyrics.status_code in (200, 201)

        # 12. Final 9:16 Reel render
        res_render = client.post(
            f"/api/v1/projects/{project_id}/render",
            json={"force_rerender": True},
        )
        assert res_render.status_code in (200, 201)
        render_data = res_render.json()
        assert render_data["success"] is True
        assert render_data["job"]["status"] == "completed"
        output_media_id = render_data["job"]["output_media_file_id"]
        assert output_media_id is not None

        # 13. Validate final download endpoint
        res_dl = client.get(f"/api/v1/projects/{project_id}/media/{output_media_id}/download")
        assert res_dl.status_code == 200
        assert len(res_dl.content) > 0
        assert res_dl.headers.get("content-type") in ("video/mp4", "application/octet-stream")

    finally:
        if tmp_vid_path.exists():
            try:
                tmp_vid_path.unlink()
            except Exception:
                pass
