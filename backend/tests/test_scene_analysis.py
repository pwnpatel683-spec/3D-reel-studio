"""
3D Reel Studio — Video Scene & Content Analysis Integration Tests
Phase 7: Video Scene & Content Analysis
"""

import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.models.project import Project, MediaFile, VideoAnalysis, VideoScene, SceneKeyframe
from app.services.audio import resolve_ffmpeg_path
from app.services.storage import get_base_storage_dir


@pytest.fixture(scope="module")
def sample_video_files(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """
    Generates synthetic deterministic test MP4 video files using FFmpeg.
    1. multi_scene_video: 4-second video with distinct color scene cut at 2.0s.
    2. single_scene_video: 2-second continuous video.
    """
    ffmpeg_bin = resolve_ffmpeg_path()
    assert ffmpeg_bin is not None, "FFmpeg must be available for video analysis test fixtures"

    temp_dir = tmp_path_factory.mktemp("scene_fixtures")
    multi_scene_path = temp_dir / "multi_scene_video.mp4"
    single_scene_path = temp_dir / "single_scene_video.mp4"

    # 1. Multi-scene video: 2s red (320x240 @ 25fps) + 2s blue (320x240 @ 25fps) -> 4s total
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2:r=25",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=25",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(multi_scene_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    # 2. Single scene video: 2s testsrc (320x240 @ 25fps)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(single_scene_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    return {
        "multi_scene": multi_scene_path,
        "single_scene": single_scene_path,
    }


@pytest.fixture
def project_with_video(client: TestClient, sample_video_files: dict):
    """
    Creates a studio project and uploads a multi-scene test video.
    """
    create_resp = client.post("/api/v1/projects", json={"name": "Scene Analysis Test Project"})
    assert create_resp.status_code == 201
    project_id = create_resp.json()["project"]["id"]

    video_path = sample_video_files["multi_scene"]
    with open(video_path, "rb") as f:
        upload_resp = client.post(
            f"/api/v1/projects/{project_id}/media",
            files={"file": ("test_multi_scene.mp4", f, "video/mp4")},
            data={"media_type": "source_video"},
        )
    assert upload_resp.status_code == 201
    media_id = upload_resp.json()["media"]["id"]

    yield {
        "project_id": project_id,
        "media_id": media_id,
        "video_path": video_path,
    }

    # Teardown
    db = SessionLocal()
    try:
        proj = db.query(Project).filter(Project.id == project_id).first()
        if proj:
            db.delete(proj)
            db.commit()
    finally:
        db.close()


def test_valid_video_analysis_and_metadata_extraction(client: TestClient, project_with_video: dict):
    """
    Scenario 1 & 2: Valid video analysis extracts accurate stream metadata and scene breakdown.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    analysis = data["analysis"]

    assert analysis["project_id"] == project_id
    assert analysis["source_media_id"] == media_id
    assert analysis["width"] == 320
    assert analysis["height"] == 240
    assert analysis["fps"] == pytest.approx(25.0, 0.1)
    assert analysis["duration"] == pytest.approx(4.0, 0.2)
    assert analysis["frame_count"] >= 90
    assert analysis["aspect_ratio"] == "4:3"
    assert analysis["codec"] == "h264"
    assert analysis["pixel_format"] == "yuv420p"


def test_scene_detection_and_timestamps(client: TestClient, project_with_video: dict):
    """
    Scenario 3, 4 & 5: Detects cut transitions, assigns sequential indices, accurate start/end timestamps and durations.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp.status_code == 200
    scenes = resp.json()["analysis"]["scenes"]

    assert len(scenes) == 2
    # Scene 0: 0.0 -> 2.0s
    assert scenes[0]["sequence"] == 0
    assert scenes[0]["start_time"] == pytest.approx(0.0, 0.05)
    assert scenes[0]["end_time"] == pytest.approx(2.0, 0.1)
    assert scenes[0]["duration"] == pytest.approx(2.0, 0.1)

    # Scene 1: 2.0 -> 4.0s
    assert scenes[1]["sequence"] == 1
    assert scenes[1]["start_time"] == pytest.approx(2.0, 0.1)
    assert scenes[1]["end_time"] == pytest.approx(4.0, 0.1)
    assert scenes[1]["duration"] == pytest.approx(2.0, 0.1)


def test_keyframe_extraction_and_timestamps(client: TestClient, project_with_video: dict):
    """
    Scenario 6 & 7: Keyframes are generated near scene midpoints, saved to disk, and linked as media files.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp.status_code == 200
    scenes = resp.json()["analysis"]["scenes"]

    base_storage = get_base_storage_dir()

    for s in scenes:
        kf = s["keyframe"]
        assert kf is not None
        assert kf["media_file_id"] != ""
        # Midpoint check: Scene 0 (midpoint ~1.0s), Scene 1 (midpoint ~3.0s)
        expected_mid = s["start_time"] + (s["duration"] / 2.0)
        assert kf["timestamp"] == pytest.approx(expected_mid, 0.1)

        # Check physical keyframe file exists on disk
        db = SessionLocal()
        try:
            kf_media = db.query(MediaFile).filter(MediaFile.id == kf["media_file_id"]).first()
            assert kf_media is not None
            assert kf_media.file_type == "keyframe_image"
            assert kf_media.mime_type == "image/jpeg"
            assert kf_media.file_size > 0

            physical_path = base_storage / kf_media.file_path
            assert physical_path.exists()
            assert physical_path.is_file()
            assert physical_path.stat().st_size == kf_media.file_size
        finally:
            db.close()


def test_video_analysis_invalid_project_404(client: TestClient):
    """
    Scenario 8: 404 when project does not exist.
    """
    resp = client.post("/api/v1/projects/PROJ-NONEXISTENT/media/MEDIA-123/analyze")
    assert resp.status_code == 404
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] in ("PROJECT_NOT_FOUND", "NOT_FOUND")


def test_video_analysis_invalid_media_404(client: TestClient, project_with_video: dict):
    """
    Scenario 9: 404 when media does not exist.
    """
    project_id = project_with_video["project_id"]
    resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-NONEXISTENT/analyze")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "MEDIA_NOT_FOUND"


def test_video_analysis_media_cross_project_rejection(client: TestClient, project_with_video: dict):
    """
    Scenario: 400 when media belongs to another project.
    """
    media_id = project_with_video["media_id"]
    other_proj_resp = client.post("/api/v1/projects", json={"name": "Other Project"})
    other_proj_id = other_proj_resp.json()["project"]["id"]

    resp = client.post(f"/api/v1/projects/{other_proj_id}/media/{media_id}/analyze")
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "MEDIA_PROJECT_MISMATCH"


def test_video_analysis_invalid_media_type_rejection(client: TestClient, project_with_video: dict):
    """
    Scenario 10: 400 when media is not a source video (e.g. face_reference or extracted_audio).
    """
    project_id = project_with_video["project_id"]

    db = SessionLocal()
    try:
        audio_media = MediaFile(
            id="MEDIA-AUDIO-TYPE-TEST",
            project_id=project_id,
            file_type="extracted_audio",
            original_filename="audio.mp3",
            stored_filename="audio.mp3",
            file_path=f"projects/{project_id}/audio/audio.mp3",
            mime_type="audio/mpeg",
            file_size=1024,
        )
        db.add(audio_media)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-AUDIO-TYPE-TEST/analyze")
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "INVALID_MEDIA_TYPE"


def test_video_analysis_missing_physical_video_file(client: TestClient, project_with_video: dict):
    """
    Scenario 11: 404 when physical source video file is deleted from disk.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    base_storage = get_base_storage_dir()
    db = SessionLocal()
    try:
        media_row = db.query(MediaFile).filter(MediaFile.id == media_id).first()
        file_path = base_storage / media_row.file_path
        if file_path.exists():
            file_path.unlink()
    finally:
        db.close()

    resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "VIDEO_FILE_NOT_FOUND"


def test_video_analysis_empty_file_rejection(client: TestClient, project_with_video: dict):
    """
    Scenario 12: 400 when source video is 0 bytes.
    """
    project_id = project_with_video["project_id"]

    base_storage = get_base_storage_dir()
    empty_file = base_storage / "projects" / project_id / "source" / "empty.mp4"
    empty_file.parent.mkdir(parents=True, exist_ok=True)
    empty_file.write_bytes(b"")

    db = SessionLocal()
    try:
        empty_media = MediaFile(
            id="MEDIA-EMPTY-VIDEO-001",
            project_id=project_id,
            file_type="source_video",
            original_filename="empty.mp4",
            stored_filename="empty.mp4",
            file_path=f"projects/{project_id}/source/empty.mp4",
            mime_type="video/mp4",
            file_size=0,
        )
        db.add(empty_media)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/v1/projects/{project_id}/media/MEDIA-EMPTY-VIDEO-001/analyze")
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "EMPTY_VIDEO_FILE"


def test_video_analysis_db_persistence_and_project_retrieval(client: TestClient, project_with_video: dict):
    """
    Scenario 13 & 14: Verifies database persistence of VideoAnalysis, VideoScene, SceneKeyframe and GET /projects/{id}.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    analyze_resp = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert analyze_resp.status_code == 200
    analysis_id = analyze_resp.json()["analysis"]["id"]

    # 1. Direct DB queries
    db = SessionLocal()
    try:
        va = db.query(VideoAnalysis).filter(VideoAnalysis.id == analysis_id).first()
        assert va is not None
        assert va.project_id == project_id
        assert va.source_media_id == media_id
        assert len(va.scenes) == 2

        for sc in va.scenes:
            assert len(sc.keyframes) == 1
            kf_row = sc.keyframes[0]
            assert kf_row.media_file_id is not None
            assert kf_row.width == 320
            assert kf_row.height == 240
    finally:
        db.close()

    # 2. Project GET retrieval endpoint
    proj_resp = client.get(f"/api/v1/projects/{project_id}")
    assert proj_resp.status_code == 200
    proj_data = proj_resp.json()["project"]
    assert "video_analyses" in proj_data
    assert len(proj_data["video_analyses"]) >= 1
    target_analysis = next((a for a in proj_data["video_analyses"] if a["id"] == analysis_id), None)
    assert target_analysis is not None
    assert len(target_analysis["scenes"]) == 2
    assert target_analysis["scenes"][0]["keyframe"] is not None


def test_video_analysis_idempotency_and_replacement(client: TestClient, project_with_video: dict):
    """
    Scenario 15: Re-running analysis for the same source media cleanly updates/replaces records without orphaned files.
    """
    project_id = project_with_video["project_id"]
    media_id = project_with_video["media_id"]

    # First analysis run
    resp1 = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp1.status_code == 200
    analysis_id_1 = resp1.json()["analysis"]["id"]
    old_kf_id_1 = resp1.json()["analysis"]["scenes"][0]["keyframe"]["media_file_id"]

    # Second analysis run (re-trigger)
    resp2 = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert resp2.status_code == 200
    analysis_id_2 = resp2.json()["analysis"]["id"]
    new_kf_id_1 = resp2.json()["analysis"]["scenes"][0]["keyframe"]["media_file_id"]

    # Verify old analysis was replaced in DB
    db = SessionLocal()
    try:
        old_va = db.query(VideoAnalysis).filter(VideoAnalysis.id == analysis_id_1).first()
        assert old_va is None, "Old analysis record should have been cleaned up"

        new_va = db.query(VideoAnalysis).filter(VideoAnalysis.id == analysis_id_2).first()
        assert new_va is not None

        old_kf_media = db.query(MediaFile).filter(MediaFile.id == old_kf_id_1).first()
        assert old_kf_media is None, "Old keyframe MediaFile record should have been deleted"

        new_kf_media = db.query(MediaFile).filter(MediaFile.id == new_kf_id_1).first()
        assert new_kf_media is not None
    finally:
        db.close()
