"""
3D Reel Studio — Production Hardening Test Suite
Phase 14: Production Hardening, Security, Storage Diagnostics & Recovery
"""

import io
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.project import (
    MediaFile,
    Project,
    RenderJob,
    TransformationJob,
    ComicGeneration,
    ConsistencyGeneration,
    SegmentationResult,
    generate_uuid,
)
from app.services.analysis import analyze_video_pipeline
from app.services.audio import extract_audio_from_video
from app.services.maintenance import (
    audit_project_storage,
    cleanup_project_storage,
    reconcile_stale_jobs_on_startup,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir


@pytest.fixture
def db_session():
    """Provides a transactional database session for tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def hardening_project(client: TestClient):
    """Creates a temporary project for hardening tests."""
    resp = client.post("/api/v1/projects", json={"name": "Hardening Test Project"})
    assert resp.status_code == 201
    proj_data = resp.json()["project"]
    proj_id = proj_data["id"]

    yield proj_id

    # Cleanup storage directory if created
    base_storage = get_base_storage_dir()
    proj_dir = base_storage / "projects" / proj_id
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)


# =============================================================================
# 1. Health & Readiness Probe Testing
# =============================================================================


def test_health_liveness_endpoint(client: TestClient):
    """Verifies that /api/v1/health returns basic liveness status without heavy checks."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["success"] is True
    assert "version" in data
    assert "service" in data


def test_readiness_probe_subsystems(client: TestClient):
    """Verifies that /api/v1/health/ready inspects database, storage, and ffmpeg without AI calls."""
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ready", "degraded")
    assert "subsystems" in data
    assert "database" in data["subsystems"]
    assert "storage" in data["subsystems"]
    assert "ffmpeg" in data["subsystems"]
    assert data["subsystems"]["database"]["status"] in ("ok", "healthy")
    assert data["subsystems"]["storage"]["status"] in ("ok", "healthy")


# =============================================================================
# 2. Storage Integrity Audit & Diagnostics
# =============================================================================


def test_storage_audit_healthy_project(client: TestClient, hardening_project: str):
    """Verifies storage audit on a clean project."""
    resp = client.get(f"/api/v1/projects/{hardening_project}/storage-audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["project_id"] == hardening_project
    assert data["is_healthy"] is True
    assert data["summary"]["total_media_records"] == 0
    assert data["summary"]["missing_count"] == 0
    assert data["summary"]["zero_byte_count"] == 0


def test_storage_audit_detects_missing_and_corrupt_files(
    client: TestClient, hardening_project: str, db_session
):
    """Verifies storage audit accurately identifies missing files and zero-byte files."""
    proj_dir = get_project_storage_dir(hardening_project, "source_video")
    proj_dir.mkdir(parents=True, exist_ok=True)

    # 1. Add record pointing to non-existent file
    missing_mf = MediaFile(
        id=generate_uuid(),
        project_id=hardening_project,
        file_type="source_video",
        original_filename="missing.mp4",
        stored_filename="missing_stored.mp4",
        file_path=f"projects/{hardening_project}/source/missing_stored.mp4",
        mime_type="video/mp4",
        file_size=1024,
    )
    db_session.add(missing_mf)

    # 2. Add record pointing to zero-byte file
    zero_path = proj_dir / "zero_byte.mp4"
    zero_path.write_bytes(b"")
    zero_mf = MediaFile(
        id=generate_uuid(),
        project_id=hardening_project,
        file_type="source_video",
        original_filename="zero.mp4",
        stored_filename="zero_byte.mp4",
        file_path=str(zero_path),
        mime_type="video/mp4",
        file_size=0,
    )
    db_session.add(zero_mf)
    db_session.commit()

    resp = client.get(f"/api/v1/projects/{hardening_project}/storage-audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_healthy"] is False
    assert data["summary"]["missing_count"] == 1
    assert data["summary"]["zero_byte_count"] == 1


# =============================================================================
# 3. Safe Storage Cleanup (Dry-Run Default)
# =============================================================================


def test_storage_cleanup_dry_run_default(client: TestClient, hardening_project: str):
    """Verifies storage cleanup dry_run=True reports stale temp directories without deleting them."""
    base_storage = get_base_storage_dir()
    stale_temp = base_storage / "projects" / hardening_project / "renders" / "tmp_job_abandoned123"
    stale_temp.mkdir(parents=True, exist_ok=True)
    dummy_file = stale_temp / "frame_001.png"
    dummy_file.write_bytes(b"temp_data")

    resp = client.post(
        f"/api/v1/projects/{hardening_project}/storage-cleanup",
        json={"dry_run": True, "clean_stale_temp": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert len(data["actions_taken"]) >= 1
    assert data["actions_taken"][0]["action"] == "would_delete_temp_dir"
    # Verify file was NOT deleted
    assert dummy_file.exists()


def test_storage_cleanup_actual_execution(client: TestClient, hardening_project: str):
    """Verifies storage cleanup dry_run=False safely removes abandoned tmp_job_* directories."""
    base_storage = get_base_storage_dir()
    stale_temp = base_storage / "projects" / hardening_project / "renders" / "tmp_job_abandoned456"
    stale_temp.mkdir(parents=True, exist_ok=True)
    dummy_file = stale_temp / "frame_002.png"
    dummy_file.write_bytes(b"temp_data_2")

    resp = client.post(
        f"/api/v1/projects/{hardening_project}/storage-cleanup",
        json={"dry_run": False, "clean_stale_temp": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is False
    assert len(data["actions_taken"]) >= 1
    assert data["actions_taken"][0]["action"] == "deleted_temp_dir"
    # Verify directory was deleted
    assert not stale_temp.exists()


# =============================================================================
# 4. Startup Stale Job Reconciliation
# =============================================================================


def test_startup_stale_job_reconciliation(db_session, hardening_project: str):
    """Verifies that stale processing jobs are safely reconciled to failed upon server restart."""
    # Create orphaned in-flight RenderJob and TransformationJob
    stale_render = RenderJob(
        id=f"rj-stale-{uuid.uuid4().hex[:8]}",
        project_id=hardening_project,
        status="processing",
        width=1080,
        height=1920,
        fps=30.0,
        video_codec="libx264",
        audio_codec="aac",
        stage_message="Processing before crash...",
    )
    stale_transform = TransformationJob(
        id=f"tj-stale-{uuid.uuid4().hex[:8]}",
        project_id=hardening_project,
        job_type="comic_style",
        status="processing",
        progress=0.45,
    )
    db_session.add(stale_render)
    db_session.add(stale_transform)
    db_session.commit()

    # Run startup reconciliation
    counts = reconcile_stale_jobs_on_startup(db_session)
    assert counts["render_jobs"] >= 1
    assert counts["transformation_jobs"] >= 1

    # Verify status changed to failed with recovery error code
    db_session.refresh(stale_render)
    db_session.refresh(stale_transform)
    assert stale_render.status == "failed"
    assert stale_render.error_code == "SERVER_RESTARTED_RECOVERY"
    assert stale_transform.status == "failed"


# =============================================================================
# 5. Media Limit Rejections (Duration, Resolution, FPS)
# =============================================================================


def test_video_analysis_rejects_exceeded_duration(hardening_project: str):
    """Verifies that analyze_video_pipeline rejects videos exceeding SOURCE_VIDEO_MAX_DURATION_SECONDS."""
    dummy_video_path = get_project_storage_dir(hardening_project, "source_video") / "test_long.mp4"
    dummy_video_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_video_path.write_bytes(b"dummy_mp4_bytes")

    from app.services.analysis import VideoMetadata
    mock_meta = VideoMetadata(
        width=1080,
        height=1920,
        fps=30.0,
        frame_count=21000,
        duration=700.0,
        codec="h264",
        pixel_format="yuv420p",
        aspect_ratio="9:16",
    )

    with patch("app.services.analysis.extract_video_metadata", return_value=mock_meta):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            analyze_video_pipeline(hardening_project, dummy_video_path)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "VIDEO_DURATION_EXCEEDED"


def test_video_analysis_rejects_exceeded_resolution(hardening_project: str):
    """Verifies that analyze_video_pipeline rejects videos exceeding resolution limits (e.g., 8K video)."""
    dummy_video_path = get_project_storage_dir(hardening_project, "source_video") / "test_8k.mp4"
    dummy_video_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_video_path.write_bytes(b"dummy_8k_bytes")

    from app.services.analysis import VideoMetadata
    mock_meta = VideoMetadata(
        width=7680,
        height=4320,
        fps=30.0,
        frame_count=300,
        duration=10.0,
        codec="h264",
        pixel_format="yuv420p",
        aspect_ratio="16:9",
    )

    with patch("app.services.analysis.extract_video_metadata", return_value=mock_meta):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            analyze_video_pipeline(hardening_project, dummy_video_path)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "VIDEO_RESOLUTION_EXCEEDED"


def test_video_analysis_rejects_exceeded_fps(hardening_project: str):
    """Verifies that analyze_video_pipeline rejects videos exceeding FPS limits (e.g., 240 fps)."""
    dummy_video_path = get_project_storage_dir(hardening_project, "source_video") / "test_highfps.mp4"
    dummy_video_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_video_path.write_bytes(b"dummy_highfps_bytes")

    from app.services.analysis import VideoMetadata
    mock_meta = VideoMetadata(
        width=1080,
        height=1920,
        fps=240.0,
        frame_count=1200,
        duration=5.0,
        codec="h264",
        pixel_format="yuv420p",
        aspect_ratio="9:16",
    )

    with patch("app.services.analysis.extract_video_metadata", return_value=mock_meta):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            analyze_video_pipeline(hardening_project, dummy_video_path)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "VIDEO_FPS_EXCEEDED"


# =============================================================================
# 6. Path Traversal Rejections
# =============================================================================


def test_path_traversal_rejections(client: TestClient):
    """Verifies that path traversal sequences in project IDs are unconditionally rejected."""
    bad_ids = [
        "../etc/passwd",
        "..\\windows\\system32",
        "project/../../secret",
        ".hidden_proj",
    ]
    for bad_id in bad_ids:
        resp = client.get(f"/api/v1/projects/{bad_id}")
        assert resp.status_code in (400, 404)

        resp = client.get(f"/api/v1/projects/{bad_id}/storage-audit")
        assert resp.status_code in (400, 404)


# =============================================================================
# 7. In-Flight Concurrency & Duplicate Protection
# =============================================================================


def test_duplicate_render_returns_in_flight_job(
    client: TestClient, hardening_project: str, db_session
):
    """Verifies that requesting a render while one is already processing returns the existing job."""
    # Seed a source video MediaFile
    source_mf = MediaFile(
        id=generate_uuid(),
        project_id=hardening_project,
        file_type="source_video",
        original_filename="source.mp4",
        stored_filename="source_video.mp4",
        file_path="projects/dummy/source_video.mp4",
        mime_type="video/mp4",
        file_size=1000,
    )
    db_session.add(source_mf)

    # Seed an in-flight RenderJob
    active_job = RenderJob(
        id=f"rj-active-{uuid.uuid4().hex[:8]}",
        project_id=hardening_project,
        status="processing",
        width=1080,
        height=1920,
        fps=30.0,
        video_codec="libx264",
        audio_codec="aac",
        stage_message="Rendering in progress...",
    )
    db_session.add(active_job)
    db_session.commit()

    resp = client.post(f"/api/v1/projects/{hardening_project}/render", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["job"]["id"] == active_job.id
    assert data["job"]["status"] == "processing"


# =============================================================================
# 8. Subprocess Timeout Safety
# =============================================================================


def test_ffmpeg_audio_timeout_handling(hardening_project: str):
    """Verifies that FFmpeg audio extraction handles subprocess.TimeoutExpired gracefully."""
    import subprocess
    dummy_source = Path(tempfile.gettempdir()) / "timeout_src.mp4"
    dummy_source.write_bytes(b"dummy")
    dummy_out = Path(tempfile.gettempdir()) / "timeout_out.mp3"

    with patch("app.services.audio.resolve_ffmpeg_path", return_value="ffmpeg"), \
         patch("app.services.audio.probe_video_has_audio", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=10)):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            extract_audio_from_video(dummy_source, dummy_out)
        assert exc_info.value.status_code == 500
        assert "timed out" in exc_info.value.detail.lower()

    if dummy_source.exists():
        dummy_source.unlink(missing_ok=True)
    if dummy_out.exists():
        dummy_out.unlink(missing_ok=True)
