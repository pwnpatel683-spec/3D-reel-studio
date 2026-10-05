"""
3D Reel Studio — Audio Extraction Integration Tests
Phase 5: FFmpeg Audio Extraction Engine
"""

import hashlib
import io
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.services.audio import resolve_ffmpeg_path, get_project_audio_dir
from app.services.storage import get_base_storage_dir


@pytest.fixture(scope="module")
def sample_media_files(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """
    Generates authentic synthetic MP4 test files with and without audio streams using FFmpeg.
    """
    ffmpeg_bin = resolve_ffmpeg_path()
    assert ffmpeg_bin is not None, "FFmpeg must be available for media test fixture"

    temp_dir = tmp_path_factory.mktemp("media_fixtures")
    video_with_audio_path = temp_dir / "video_with_audio.mp4"
    video_no_audio_path = temp_dir / "video_no_audio.mp4"

    # 1. Generate 1-second test video WITH audio (sine wave 1000Hz)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(video_with_audio_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    # 2. Generate 1-second test video WITHOUT audio (-an flag)
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=15",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            str(video_no_audio_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    return {
        "with_audio_bytes": video_with_audio_path.read_bytes(),
        "no_audio_bytes": video_no_audio_path.read_bytes(),
    }


def create_project_and_upload_video(client: TestClient, video_bytes: bytes, filename: str = "source.mp4") -> tuple:
    """Helper to create project, upload video, and return (project_id, media_id)."""
    proj_res = client.post("/api/v1/projects", json={"name": "Audio Extraction Test Project"})
    assert proj_res.status_code == 201
    project_id = proj_res.json()["project"]["id"]

    upload_res = client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": (filename, io.BytesIO(video_bytes), "video/mp4")},
        data={"media_type": "source_video"},
    )
    assert upload_res.status_code == 201
    media_id = upload_res.json()["media"]["id"]
    return project_id, media_id


# 1. Valid video containing audio (Successful extraction)
def test_audio_extraction_valid_video_success(client: TestClient, sample_media_files: dict) -> None:
    project_id, media_id = create_project_and_upload_video(
        client, sample_media_files["with_audio_bytes"], "clip_with_sound.mp4"
    )

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 201
    data = res.json()
    assert data["success"] is True
    media = data["media"]
    assert media["project_id"] == project_id
    assert media["file_type"] == "extracted_audio"
    assert media["original_filename"] == "clip_with_sound_audio.mp3"
    assert media["stored_filename"].endswith(".mp3")
    assert media["mime_type"] == "audio/mpeg"
    assert media["file_size"] > 0
    assert media["sha256_hash"] is not None
    assert "id" in media


# 2. Video without audio stream
def test_audio_extraction_video_without_audio_stream(client: TestClient, sample_media_files: dict) -> None:
    project_id, media_id = create_project_and_upload_video(
        client, sample_media_files["no_audio_bytes"], "silent_video.mp4"
    )

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 400
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NO_AUDIO_STREAM"
    assert "does not contain an audio stream" in data["error"]["message"].lower()


# 3. Invalid project
def test_audio_extraction_invalid_project_404(client: TestClient) -> None:
    res = client.post("/api/v1/projects/PROJ-DOESNOTEXIST99/media/some-media-id/extract-audio")
    assert res.status_code == 404
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"
    assert "not found" in data["error"]["message"].lower()


# 4. Invalid media
def test_audio_extraction_invalid_media_404(client: TestClient) -> None:
    proj_res = client.post("/api/v1/projects", json={"name": "Missing Media Project"})
    project_id = proj_res.json()["project"]["id"]

    res = client.post(f"/api/v1/projects/{project_id}/media/media-uuid-nonexistent/extract-audio")
    assert res.status_code == 404
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"


# 5. Media belonging to another project
def test_audio_extraction_media_cross_project_rejection(client: TestClient, sample_media_files: dict) -> None:
    proj1_id, media1_id = create_project_and_upload_video(client, sample_media_files["with_audio_bytes"])

    proj2_res = client.post("/api/v1/projects", json={"name": "Second Project"})
    proj2_id = proj2_res.json()["project"]["id"]

    # Attempt to extract media1 using proj2_id
    res = client.post(f"/api/v1/projects/{proj2_id}/media/{media1_id}/extract-audio")
    assert res.status_code == 400
    data = res.json()
    assert data["success"] is False
    assert "does not belong to project" in data["error"]["message"]


# 6. Invalid media type (face reference cannot extract audio)
def test_audio_extraction_invalid_media_type_rejection(client: TestClient) -> None:
    proj_res = client.post("/api/v1/projects", json={"name": "Image Project"})
    project_id = proj_res.json()["project"]["id"]

    # Upload face reference image
    img_bytes = b"\x89PNG\r\n\x1a\n" + b"dummy_png" * 10
    upload_res = client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("face.png", io.BytesIO(img_bytes), "image/png")},
        data={"media_type": "face_reference"},
    )
    assert upload_res.status_code == 201
    media_id = upload_res.json()["media"]["id"]

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 400
    data = res.json()
    assert data["success"] is False
    assert "not a source video" in data["error"]["message"].lower()


# 7. Missing source physical file on disk
def test_audio_extraction_missing_source_file(client: TestClient, sample_media_files: dict) -> None:
    project_id, media_id = create_project_and_upload_video(client, sample_media_files["with_audio_bytes"])

    # Retrieve physical path and delete it manually from storage
    get_res = client.get(f"/api/v1/projects/{project_id}")
    stored_filename = get_res.json()["project"]["media_files"][0]["stored_filename"]
    base_storage = get_base_storage_dir()
    physical_video = base_storage / "projects" / project_id / "source" / stored_filename

    if physical_video.exists():
        physical_video.unlink()

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 404
    data = res.json()
    assert data["success"] is False
    assert "missing" in data["error"]["message"].lower()


# 8. FFmpeg unavailable handling
def test_audio_extraction_ffmpeg_unavailable_handling(
    client: TestClient, sample_media_files: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, media_id = create_project_and_upload_video(client, sample_media_files["with_audio_bytes"])

    # Point FFMPEG_PATH to non-existent executable
    monkeypatch.setattr(settings, "FFMPEG_PATH", "non_existent_ffmpeg_executable_bin_12345")
    # Also mock resolve_ffmpeg_path to return None
    import app.services.audio as audio_mod
    monkeypatch.setattr(audio_mod, "resolve_ffmpeg_path", lambda: None)

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 503
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "SERVICE_UNAVAILABLE"


# 9. Database MediaFile record & physical audio file on storage
def test_audio_extraction_db_and_physical_file(client: TestClient, sample_media_files: dict) -> None:
    project_id, media_id = create_project_and_upload_video(
        client, sample_media_files["with_audio_bytes"], "soundtrack.mp4"
    )

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 201
    media = res.json()["media"]

    # Verify physical file existence and content
    base_storage = get_base_storage_dir()
    audio_path = base_storage / "projects" / project_id / "audio" / media["stored_filename"]
    assert audio_path.exists()
    assert audio_path.is_file()
    assert audio_path.stat().st_size == media["file_size"]

    # Verify SHA-256 hash matches disk file
    content = audio_path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == media["sha256_hash"]


# 10. Project detail includes extracted audio metadata
def test_project_retrieval_includes_extracted_audio(client: TestClient, sample_media_files: dict) -> None:
    project_id, media_id = create_project_and_upload_video(
        client, sample_media_files["with_audio_bytes"], "cinematic.mp4"
    )

    # Extract audio
    extract_res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert extract_res.status_code == 201

    # Fetch project details
    get_res = client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 200
    project = get_res.json()["project"]
    assert len(project["media_files"]) == 2

    file_types = [m["file_type"] for m in project["media_files"]]
    assert "source_video" in file_types
    assert "extracted_audio" in file_types

    # Ensure no absolute paths are leaked
    for m in project["media_files"]:
        assert "file_path" not in m
        assert "original_filename" in m
        assert "stored_filename" in m


# 11. Cleanup of generated file if DB insertion fails
def test_audio_extraction_cleanup_on_db_failure(
    client: TestClient, sample_media_files: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, media_id = create_project_and_upload_video(client, sample_media_files["with_audio_bytes"])

    # Mock db.commit to raise an exception simulating database failure
    from sqlalchemy.orm import Session
    orig_commit = Session.commit

    def mock_commit(self):
        raise RuntimeError("Simulated Database Commit Error")

    monkeypatch.setattr(Session, "commit", mock_commit)

    res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/extract-audio")
    assert res.status_code == 500
    assert res.json()["success"] is False

    # Verify no orphaned audio files remain in project audio folder
    audio_dir = get_project_audio_dir(project_id)
    created_files = list(audio_dir.glob("*.mp3"))
    assert len(created_files) == 0
