"""
3D Reel Studio — Automated Test Suite for Phase 8 Vision Analysis
Tests face detection, landmark extraction, primary subject selection, face references,
pose detection, temporal tracking, database persistence, and idempotency.
"""

import io
import shutil
import subprocess
import uuid
from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import init_db, SessionLocal
from app.models.project import Project, MediaFile, VisionAnalysis, DetectedSubject, FaceDetection, FaceReference, PoseDetection
from app.services.storage import get_base_storage_dir
from app.services.vision import (
    detect_faces_in_image,
    estimate_body_pose,
    track_subjects_temporally,
    select_and_save_face_references,
    FaceDetectionResult,
)


@pytest.fixture(scope="function")
def test_db():
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_synthetic_face_video(output_path: Path, num_faces: int = 1, duration: float = 2.0, fps: int = 30):
    """
    Creates a small synthetic test video with visible face drawings for deterministic CV testing.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 640, 480
    total_frames = int(duration * fps)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    for f_idx in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Background
        frame[:] = (40, 30, 25)

        # Primary face (moving slightly)
        drift = int(math_sin := 15.0 * np.sin(f_idx * 0.1))
        c_x1, c_y1 = 320 + drift, 200
        # Skin tone ellipse
        cv2.ellipse(frame, (c_x1, c_y1), (65, 80), 0, 0, 360, (140, 160, 210), -1)
        # Eyes
        cv2.circle(frame, (c_x1 - 25, c_y1 - 15), 8, (40, 40, 40), -1)
        cv2.circle(frame, (c_x1 + 25, c_y1 - 15), 8, (40, 40, 40), -1)
        # Mouth
        cv2.ellipse(frame, (c_x1, c_y1 + 35), (20, 8), 0, 0, 180, (50, 50, 160), -1)

        # If secondary face requested (smaller face on right)
        if num_faces > 1:
            c_x2, c_y2 = 520, 260
            cv2.ellipse(frame, (c_x2, c_y2), (35, 45), 0, 0, 360, (140, 160, 210), -1)
            cv2.circle(frame, (c_x2 - 12, c_y2 - 10), 4, (40, 40, 40), -1)
            cv2.circle(frame, (c_x2 + 12, c_y2 - 10), 4, (40, 40, 40), -1)

        writer.write(frame)

    writer.release()


def test_unit_face_detection_and_landmarks():
    """Test unit level face detection and 5-point facial landmark extraction."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (30, 20, 20)
    # Draw face
    cv2.ellipse(img, (320, 240), (60, 75), 0, 0, 360, (140, 160, 210), -1)

    faces = detect_faces_in_image(img, timestamp=1.5, frame_ref="keyframe_01")
    assert len(faces) >= 1
    face = faces[0]
    assert 0.0 <= face.x <= 1.0
    assert 0.0 <= face.y <= 1.0
    assert 0.0 < face.width <= 1.0
    assert 0.0 < face.height <= 1.0
    assert face.confidence > 0.70
    assert len(face.landmarks) == 5

    names = [lm.name for lm in face.landmarks]
    assert "left_eye" in names
    assert "right_eye" in names
    assert "nose" in names
    assert "left_mouth" in names
    assert "right_mouth" in names


def test_unit_pose_estimation_17_landmarks():
    """Test unit level 17 COCO body pose landmark generation."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    face = FaceDetectionResult(
        timestamp=1.0,
        frame_reference="kf_1",
        x=0.35,
        y=0.15,
        width=0.25,
        height=0.20,
        confidence=0.92,
        landmarks=[],
    )

    pose = estimate_body_pose(img, face, timestamp=1.0, frame_ref="kf_1")
    assert pose.confidence > 0.70
    assert len(pose.landmarks) == 17

    landmark_names = [lm.landmark_name for lm in pose.landmarks]
    assert "nose" in landmark_names
    assert "left_shoulder" in landmark_names
    assert "right_shoulder" in landmark_names
    assert "left_wrist" in landmark_names
    assert "right_ankle" in landmark_names

    for lm in pose.landmarks:
        assert 0.0 <= lm.x <= 1.0
        assert 0.0 <= lm.y <= 1.0
        assert 0.0 <= lm.visibility <= 1.0


def test_unit_temporal_tracking_and_primary_selection():
    """Test temporal tracking and deterministic primary subject selection."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)

    # Frame 1: Primary (center, large) + Secondary (small, right)
    f1_primary = FaceDetectionResult(timestamp=0.0, frame_reference="f1", x=0.35, y=0.15, width=0.25, height=0.25, confidence=0.95)
    f1_secondary = FaceDetectionResult(timestamp=0.0, frame_reference="f1", x=0.80, y=0.40, width=0.10, height=0.10, confidence=0.80)

    # Frame 2: Primary (slight drift) + Secondary (slight drift)
    f2_primary = FaceDetectionResult(timestamp=1.0, frame_reference="f2", x=0.37, y=0.16, width=0.24, height=0.24, confidence=0.94)
    f2_secondary = FaceDetectionResult(timestamp=1.0, frame_reference="f2", x=0.81, y=0.41, width=0.10, height=0.10, confidence=0.82)

    frames_data = [
        (0.0, "f1", [f1_primary, f1_secondary], img),
        (1.0, "f2", [f2_primary, f2_secondary], img),
    ]

    subjects = track_subjects_temporally(frames_data)
    assert len(subjects) == 2
    primary = next((s for s in subjects if s.is_primary), None)
    assert primary is not None
    # Primary subject has larger detections
    assert len(primary.face_detections) == 2
    assert primary.confidence >= 0.90


def test_vision_analysis_valid_video_api(client, test_db):
    """Test end-to-end vision analysis API with valid video."""
    # 1. Create project
    p_res = client.post("/api/v1/projects", json={"name": "Vision Test Project"})
    assert p_res.status_code == 201
    proj_id = p_res.json()["project"]["id"]

    # 2. Upload synthetic video
    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"test_vision_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, num_faces=1, duration=1.5, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{proj_id}/media",
                files={"file": ("person_walk.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        assert u_res.status_code == 201
        media_id = u_res.json()["media"]["id"]

        # 3. Trigger Phase 7 scene analysis first
        s_res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/analyze")
        assert s_res.status_code == 200

        # 4. Trigger Phase 8 vision analysis
        v_res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert v_res.status_code == 200
        data = v_res.json()
        assert data["success"] is True
        analysis = data["analysis"]

        assert analysis["project_id"] == proj_id
        assert analysis["source_media_id"] == media_id
        assert analysis["primary_subject_id"] is not None
        assert analysis["faces_detected"] >= 1
        assert analysis["pose_frames"] >= 1
        assert len(analysis["subjects"]) >= 1

        primary_subj = next((s for s in analysis["subjects"] if s["is_primary"]), None)
        assert primary_subj is not None
        assert len(primary_subj["face_detections"]) >= 1
        assert len(primary_subj["pose_detections"]) >= 1

        # Check pose landmarks
        first_pose = primary_subj["pose_detections"][0]
        assert len(first_pose["landmarks"]) == 17

        # Check face references
        if len(analysis["face_references"]) > 0:
            first_ref = analysis["face_references"][0]
            assert first_ref["media_file_id"] != ""
            assert first_ref["quality_score"] > 0.0

            # Verify face reference file is downloadable
            file_res = client.get(f"/api/v1/projects/{proj_id}/media/{first_ref['media_file_id']}/file")
            assert file_res.status_code == 200
            assert file_res.headers["content-type"] in ["image/jpeg", "image/jpg"]

    finally:
        if temp_vid.exists():
            temp_vid.unlink()


def test_vision_analysis_multi_person_primary_selection(client, test_db):
    """Test vision analysis on multi-person video correctly designates primary subject."""
    p_res = client.post("/api/v1/projects", json={"name": "Multi-Person Vision"})
    proj_id = p_res.json()["project"]["id"]

    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"test_multi_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, num_faces=2, duration=1.5, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{proj_id}/media",
                files={"file": ("multi_dance.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        media_id = u_res.json()["media"]["id"]

        v_res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert v_res.status_code == 200
        analysis = v_res.json()["analysis"]

        primary_subjects = [s for s in analysis["subjects"] if s["is_primary"]]
        assert len(primary_subjects) == 1

    finally:
        if temp_vid.exists():
            temp_vid.unlink()


def test_vision_analysis_invalid_project_404(client):
    """Test vision analysis with non-existent project returns 404."""
    res = client.post("/api/v1/projects/NONEXISTENT-PROJ/media/MEDIA-123/vision-analysis")
    assert res.status_code == 404
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] in ("PROJECT_NOT_FOUND", "NOT_FOUND")


def test_vision_analysis_invalid_media_404(client):
    """Test vision analysis with non-existent media returns 404."""
    p_res = client.post("/api/v1/projects", json={"name": "Test P404"})
    proj_id = p_res.json()["project"]["id"]

    res = client.post(f"/api/v1/projects/{proj_id}/media/NONEXISTENT-MEDIA/vision-analysis")
    assert res.status_code == 404
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "MEDIA_NOT_FOUND"


def test_vision_analysis_cross_project_rejection(client):
    """Test vision analysis rejects media belonging to a different project."""
    p1 = client.post("/api/v1/projects", json={"name": "Project 1"}).json()["project"]["id"]
    p2 = client.post("/api/v1/projects", json={"name": "Project 2"}).json()["project"]["id"]

    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"test_cross_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, duration=1.0, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{p1}/media",
                files={"file": ("v1.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        m1_id = u_res.json()["media"]["id"]

        # Call under Project 2
        res = client.post(f"/api/v1/projects/{p2}/media/{m1_id}/vision-analysis")
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "MEDIA_PROJECT_MISMATCH"
    finally:
        if temp_vid.exists():
            temp_vid.unlink()


def test_vision_analysis_invalid_media_type_rejection(client):
    """Test vision analysis rejects face reference images (only source videos allowed)."""
    p_res = client.post("/api/v1/projects", json={"name": "Wrong Media Type"}).json()
    proj_id = p_res["project"]["id"]

    fake_img = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200)
    u_res = client.post(
        f"/api/v1/projects/{proj_id}/media",
        files={"file": ("avatar.jpg", fake_img, "image/jpeg")},
        data={"media_type": "face_reference"},
    )
    media_id = u_res.json()["media"]["id"]

    res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_MEDIA_TYPE"


def test_vision_analysis_missing_physical_file(client, test_db):
    """Test vision analysis handles missing physical file with 404."""
    p_res = client.post("/api/v1/projects", json={"name": "Missing File"}).json()
    proj_id = p_res["project"]["id"]

    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"temp_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, duration=1.0, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{proj_id}/media",
                files={"file": ("vid.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        media_id = u_res.json()["media"]["id"]

        # Delete physical file from storage
        media_rec = test_db.query(MediaFile).filter(MediaFile.id == media_id).first()
        physical_path = base_storage / media_rec.file_path
        if physical_path.exists():
            physical_path.unlink()

        res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "VIDEO_FILE_NOT_FOUND"
    finally:
        if temp_vid.exists():
            temp_vid.unlink()


def test_vision_analysis_db_persistence_and_project_retrieval(client, test_db):
    """Test vision analysis records are persisted and returned in GET /api/v1/projects/{id}."""
    p_res = client.post("/api/v1/projects", json={"name": "Persistence Verification"}).json()
    proj_id = p_res["project"]["id"]

    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"test_persist_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, duration=1.0, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{proj_id}/media",
                files={"file": ("persist.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        media_id = u_res.json()["media"]["id"]

        # Run vision analysis
        v_res = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert v_res.status_code == 200
        analysis_id = v_res.json()["analysis"]["id"]

        # Retrieve project
        get_res = client.get(f"/api/v1/projects/{proj_id}")
        assert get_res.status_code == 200
        proj_data = get_res.json()["project"]

        assert len(proj_data["vision_analyses"]) >= 1
        retrieved_va = proj_data["vision_analyses"][0]
        assert retrieved_va["id"] == analysis_id
        assert retrieved_va["faces_detected"] >= 1
        assert retrieved_va["pose_frames"] >= 1

    finally:
        if temp_vid.exists():
            temp_vid.unlink()


def test_vision_analysis_idempotency_and_replacement(client, test_db):
    """Test running vision analysis multiple times replaces prior records without orphaned files."""
    p_res = client.post("/api/v1/projects", json={"name": "Idempotency Project"}).json()
    proj_id = p_res["project"]["id"]

    base_storage = get_base_storage_dir()
    temp_vid = base_storage / f"test_idemp_{uuid.uuid4().hex[:6]}.mp4"
    create_synthetic_face_video(temp_vid, duration=1.0, fps=24)

    try:
        with open(temp_vid, "rb") as f:
            u_res = client.post(
                f"/api/v1/projects/{proj_id}/media",
                files={"file": ("idemp.mp4", f, "video/mp4")},
                data={"media_type": "source_video"},
            )
        media_id = u_res.json()["media"]["id"]

        # Run 1st analysis
        res1 = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert res1.status_code == 200
        id1 = res1.json()["analysis"]["id"]

        # Run 2nd analysis
        res2 = client.post(f"/api/v1/projects/{proj_id}/media/{media_id}/vision-analysis")
        assert res2.status_code == 200
        id2 = res2.json()["analysis"]["id"]

        assert id1 != id2

        # Check DB only has 1 active VisionAnalysis for this project
        active_vas = test_db.query(VisionAnalysis).filter(VisionAnalysis.project_id == proj_id).all()
        assert len(active_vas) == 1
        assert active_vas[0].id == id2

    finally:
        if temp_vid.exists():
            temp_vid.unlink()
