"""
3D Reel Studio — Media Upload & Secure Storage Integration Tests
Phase 4: Media Upload & Secure File Storage
"""

import hashlib
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.services.storage import get_base_storage_dir, get_project_storage_dir


def create_dummy_project(client: TestClient, name: str = "Test Studio Project") -> str:
    """Helper to create a project and return its ID."""
    res = client.post("/api/v1/projects", json={"name": name})
    assert res.status_code == 201
    return res.json()["project"]["id"]


# 1. Valid MP4 upload
def test_upload_valid_mp4_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "MP4 Test Project")
    content = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"mp4_sample_data" * 10
    file_payload = {"file": ("test_video.mp4", io.BytesIO(content), "video/mp4")}
    data_payload = {"media_type": "source_video"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    body = res.json()
    assert body["success"] is True
    media = body["media"]
    assert media["project_id"] == project_id
    assert media["file_type"] == "source_video"
    assert media["original_filename"] == "test_video.mp4"
    assert media["stored_filename"].endswith(".mp4")
    assert media["mime_type"] == "video/mp4"
    assert media["file_size"] == len(content)
    assert media["sha256_hash"] == hashlib.sha256(content).hexdigest()
    assert "id" in media
    assert "created_at" in media


# 2. Valid MOV upload
def test_upload_valid_mov_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "MOV Test Project")
    content = b"\x00\x00\x00\x14ftypqt  " + b"mov_sample_video_payload" * 5
    file_payload = {"file": ("clip.mov", io.BytesIO(content), "video/quicktime")}
    data_payload = {"media_type": "source_video"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    media = res.json()["media"]
    assert media["original_filename"] == "clip.mov"
    assert media["stored_filename"].endswith(".mov")
    assert media["file_type"] == "source_video"


# 3. Valid WEBM upload
def test_upload_valid_webm_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "WEBM Test Project")
    content = b"\x1a\x45\xdf\xa3" + b"webm_sample_video_stream" * 8
    file_payload = {"file": ("animation.webm", io.BytesIO(content), "video/webm")}
    data_payload = {"media_type": "source_video"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    media = res.json()["media"]
    assert media["original_filename"] == "animation.webm"
    assert media["stored_filename"].endswith(".webm")
    assert media["file_type"] == "source_video"


# 4. Valid JPG upload
def test_upload_valid_jpg_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "JPG Test Project")
    content = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"jpg_face_data" * 10
    file_payload = {"file": ("portrait.jpg", io.BytesIO(content), "image/jpeg")}
    data_payload = {"media_type": "face_reference"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    media = res.json()["media"]
    assert media["file_type"] == "face_reference"
    assert media["original_filename"] == "portrait.jpg"
    assert media["stored_filename"].endswith(".jpg")
    assert media["file_size"] == len(content)


# 5. Valid JPEG upload
def test_upload_valid_jpeg_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "JPEG Test Project")
    content = b"\xff\xd8\xff\xe1" + b"jpeg_face_data" * 10
    file_payload = {"file": ("actor.jpeg", io.BytesIO(content), "image/jpeg")}
    data_payload = {"media_type": "face_reference"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    media = res.json()["media"]
    assert media["file_type"] == "face_reference"
    assert media["original_filename"] == "actor.jpeg"
    assert media["stored_filename"].endswith(".jpeg")


# 6. Valid PNG upload
def test_upload_valid_png_success(client: TestClient) -> None:
    project_id = create_dummy_project(client, "PNG Test Project")
    content = b"\x89PNG\r\n\x1a\n" + b"png_character_face" * 10
    file_payload = {"file": ("avatar.png", io.BytesIO(content), "image/png")}
    data_payload = {"media_type": "face_reference"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 201
    media = res.json()["media"]
    assert media["file_type"] == "face_reference"
    assert media["original_filename"] == "avatar.png"
    assert media["stored_filename"].endswith(".png")


# 7. Unsupported file rejection
def test_upload_unsupported_file_rejection(client: TestClient) -> None:
    project_id = create_dummy_project(client, "Unsupported File Project")

    # Disallowed text file as video
    res = client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("malicious.txt", io.BytesIO(b"hello world"), "text/plain")},
        data={"media_type": "source_video"},
    )
    assert res.status_code == 400
    assert res.json()["success"] is False
    assert "Unsupported file extension" in res.json()["error"]["message"]

    # Disallowed executable as face reference
    res2 = client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("script.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
        data={"media_type": "face_reference"},
    )
    assert res2.status_code == 400
    assert res2.json()["success"] is False

    # Invalid media_type string
    res3 = client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("video.mp4", io.BytesIO(b"data"), "video/mp4")},
        data={"media_type": "unknown_type"},
    )
    assert res3.status_code == 400
    assert res3.json()["success"] is False
    assert "Invalid media_type" in res3.json()["error"]["message"]


# 8. Empty file rejection
def test_upload_empty_file_rejection(client: TestClient) -> None:
    project_id = create_dummy_project(client, "Empty File Project")
    file_payload = {"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")}
    data_payload = {"media_type": "source_video"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 400
    assert res.json()["success"] is False
    assert "empty" in res.json()["error"]["message"].lower()


# 9. Oversized file rejection
def test_upload_oversized_file_rejection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = create_dummy_project(client, "Oversized File Project")

    # Set temporary small limit (1 MB) to test limit enforcement safely
    monkeypatch.setattr(settings, "FACE_REFERENCE_MAX_SIZE_MB", 1)

    # 1.5 MB payload
    oversized_data = b"X" * int(1.5 * 1024 * 1024)
    file_payload = {"file": ("large_face.png", io.BytesIO(oversized_data), "image/png")}
    data_payload = {"media_type": "face_reference"}

    res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert res.status_code == 413
    assert res.json()["success"] is False
    assert "exceeds maximum allowed size" in res.json()["error"]["message"].lower()


# 10. Invalid project rejection
def test_upload_invalid_project_rejection(client: TestClient) -> None:
    file_payload = {"file": ("test.mp4", io.BytesIO(b"dummy video data"), "video/mp4")}
    data_payload = {"media_type": "source_video"}

    res = client.post("/api/v1/projects/PROJ-NONEXISTENT999/media", files=file_payload, data=data_payload)
    assert res.status_code == 404
    assert res.json()["success"] is False
    assert res.json()["error"]["code"] == "NOT_FOUND"


# 11. Successful database MediaFile record
def test_upload_database_mediafile_record(client: TestClient) -> None:
    project_id = create_dummy_project(client, "DB Media Record Project")
    content = b"sample video database test" * 20
    file_payload = {"file": ("db_test.mp4", io.BytesIO(content), "video/mp4")}
    data_payload = {"media_type": "source_video"}

    upload_res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert upload_res.status_code == 201
    media = upload_res.json()["media"]

    # Verify attributes returned from DB
    assert media["id"] is not None
    assert media["project_id"] == project_id
    assert media["file_type"] == "source_video"
    assert media["original_filename"] == "db_test.mp4"
    assert media["file_size"] == len(content)
    assert media["sha256_hash"] == hashlib.sha256(content).hexdigest()
    assert media["created_at"] is not None


# 12. Successful physical file storage
def test_upload_physical_file_storage(client: TestClient) -> None:
    project_id = create_dummy_project(client, "Physical Storage Test")
    content = b"secure physical bytes verification content" * 15
    file_payload = {"file": ("verify_disk.png", io.BytesIO(content), "image/png")}
    data_payload = {"media_type": "face_reference"}

    upload_res = client.post(f"/api/v1/projects/{project_id}/media", files=file_payload, data=data_payload)
    assert upload_res.status_code == 201
    stored_name = upload_res.json()["media"]["stored_filename"]

    # Check physical file on filesystem
    base_storage = get_base_storage_dir()
    expected_path = base_storage / "projects" / project_id / "face-reference" / stored_name
    assert expected_path.exists()
    assert expected_path.is_file()
    assert expected_path.read_bytes() == content


# 13. Project retrieval includes media
def test_project_retrieval_includes_media(client: TestClient) -> None:
    project_id = create_dummy_project(client, "Complete Project Retrieval")

    # Upload video
    client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("main_reel.mp4", io.BytesIO(b"reel content"), "video/mp4")},
        data={"media_type": "source_video"},
    )

    # Upload face reference
    client.post(
        f"/api/v1/projects/{project_id}/media",
        files={"file": ("reference.jpg", io.BytesIO(b"face image"), "image/jpeg")},
        data={"media_type": "face_reference"},
    )

    # Retrieve project
    get_res = client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["success"] is True
    project = data["project"]
    assert len(project["media_files"]) == 2

    types = [m["file_type"] for m in project["media_files"]]
    assert "source_video" in types
    assert "face_reference" in types

    # Check that absolute filesystem paths are NOT exposed
    for m in project["media_files"]:
        assert "file_path" not in m
        assert "original_filename" in m
        assert "stored_filename" in m


# 14. Path traversal protection
def test_path_traversal_protection(client: TestClient) -> None:
    # Attempting path traversal in project_id
    traversal_ids = ["../../etc", "..%2F..%2Fetc", "/etc/passwd", "..\\..\\windows"]
    file_payload = {"file": ("test.mp4", io.BytesIO(b"test"), "video/mp4")}
    data_payload = {"media_type": "source_video"}

    for tid in traversal_ids:
        res = client.post(f"/api/v1/projects/{tid}/media", files=file_payload, data=data_payload)
        # Should be blocked with 400 Bad Request or 404
        assert res.status_code in {400, 404}
        assert res.json()["success"] is False

    # Direct check on get_project_storage_dir security
    with pytest.raises(Exception):
        get_project_storage_dir("../../../outside", "source_video")
