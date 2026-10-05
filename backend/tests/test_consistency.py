"""
3D Reel Studio — Identity + Temporal Consistency Engine Tests
Phase 10: Reference-Guided Visual Consistency & Temporal Chaining
"""

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.main import app
from app.models.project import (
    CharacterConsistencyProfile,
    ConsistencyGeneration,
    ConsistentComicFrame,
    Project,
)
from app.services.comic_generation import (
    MockComicProvider,
    OpenAIComicProvider,
    get_comic_generation_provider,
)
from app.services.consistency import (
    CharacterConsistencyService,
    build_stable_character_descriptor,
    select_canonical_and_multi_references,
)

from tests.conftest import get_test_auth_headers

client = TestClient(app, headers=get_test_auth_headers())


def create_synthetic_test_video(output_path: Path, duration: float = 2.0, fps: int = 30) -> Path:
    """Creates a deterministic test video with facial features for testing."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 640, 480
    total_frames = int(duration * fps)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    for i in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (40, 30, 20)  # Dark background

        # Draw a face (skin ellipse in BGR format)
        cv2.ellipse(frame, (320, 240), (80, 110), 0, 0, 360, (140, 175, 230), -1)
        # Eyes
        cv2.circle(frame, (290, 210), 10, (20, 20, 20), -1)
        cv2.circle(frame, (350, 210), 10, (20, 20, 20), -1)
        # Nose
        cv2.line(frame, (320, 220), (320, 250), (40, 40, 40), 3)
        # Mouth
        cv2.ellipse(frame, (320, 280), (30, 12), 0, 0, 180, (50, 50, 180), 3)

        writer.write(frame)

    writer.release()
    return output_path


# -----------------------------------------------------------------------------
# 1-7: Unit Tests: Canonical & Multi-Reference Selection, Descriptors, Prompts
# -----------------------------------------------------------------------------

def test_canonical_and_multi_reference_selection():
    """Verify selection of canonical reference and non-fabricated multi-angle sorting."""
    # Dummy mock face references with varying quality and landmark positions
    face_refs = [
        MagicMock(
            id="ref-1",
            media_file_id="mf-1",
            timestamp=1.0,
            quality_score=0.85,
            face_detection=MagicMock(confidence=0.90, bbox_width=120, bbox_height=150, landmarks={"left_eye": [100, 100], "right_eye": [160, 100], "nose_tip": [130, 130]}),
        ),
        MagicMock(
            id="ref-2",
            media_file_id="mf-2",
            timestamp=2.5,
            quality_score=0.98,
            face_detection=MagicMock(confidence=0.99, bbox_width=160, bbox_height=200, landmarks={"left_eye": [100, 100], "right_eye": [160, 100], "nose_tip": [130, 130]}),
        ),
        MagicMock(
            id="ref-3",
            media_file_id="mf-3",
            timestamp=4.0,
            quality_score=0.75,
            face_detection=MagicMock(confidence=0.85, bbox_width=100, bbox_height=120, landmarks={"left_eye": [100, 100], "right_eye": [160, 100], "nose_tip": [115, 130]}), # angled left
        ),
    ]

    canonical, angle_dict = select_canonical_and_multi_references(face_refs)
    assert canonical is not None
    assert canonical.id == "ref-2"  # Highest quality frontal score
    assert "frontal" in angle_dict
    assert angle_dict["frontal"] == "ref-2"
    assert "angled_left" in angle_dict
    assert "angled_right" in angle_dict


def test_canonical_selection_empty_fallback():
    """Verify empty face references return None gracefully without errors."""
    canonical, angle_dict = select_canonical_and_multi_references([])
    assert canonical is None
    assert angle_dict["frontal"] is None


def test_build_stable_character_descriptor():
    """Verify generation of non-sensitive, project-local visual descriptors."""
    subj = MagicMock(
        is_primary=True,
        confidence=0.95,
        attributes={"clothing_color": "dark_jacket", "lighting": "cinematic_neon"},
    )
    descriptor = build_stable_character_descriptor(
        primary_subject=subj,
        canonical_ref=MagicMock(id="ref-2"),
    )
    assert "facial_structure" in descriptor
    assert "clothing_continuity" in descriptor
    # Ensure no sensitive claims
    desc_str = str(descriptor).lower()
    assert "ethnicity" not in desc_str
    assert "religion" not in desc_str


def test_build_consistent_comic_prompt_with_style_lock():
    """Verify prompt builder applies versioned style preset and temporal chaining cues."""
    dummy_scene = MagicMock(sequence=2, start_time=1.5, end_time=3.0)
    dummy_profile = MagicMock(
        descriptor_metadata={
            "style_lock_version": "v1-3d-comic-lock",
            "facial_structure": "stylized 3D character with defined jawline",
            "clothing_continuity": "dark cyber jacket",
        }
    )
    prompt, version = CharacterConsistencyService.construct_consistent_prompt(
        scene=dummy_scene,
        sequence_index=2,
        profile=dummy_profile,
        pose_summary="standing heroically facing camera",
        style_preset="3d-comic",
        prompt_override="cinematic neon lighting",
    )
    assert "v1-3d-comic-lock" in version
    assert "3D comic illustration" in prompt
    assert "dark cyber jacket" in prompt
    assert "standing heroically" in prompt
    assert "cinematic neon lighting" in prompt


def test_calculate_non_identifying_diagnostics_success(tmp_path: Path):
    """Verify visual diagnostics return safe face detection and histogram correlation scores."""
    # Create test image in bytes
    im1 = np.zeros((1792, 1024, 3), dtype=np.uint8)
    cv2.ellipse(im1, (512, 600), (200, 260), 0, 0, 360, (140, 175, 230), -1)
    _, buf = cv2.imencode(".png", im1)
    img_bytes = buf.tobytes()

    # Reference file
    ref_path = tmp_path / "ref.png"
    cv2.imwrite(str(ref_path), im1)

    diag = CharacterConsistencyService.calculate_consistency_diagnostics(
        output_image_bytes=img_bytes,
        canonical_ref_path=ref_path,
        expected_width=1024,
        expected_height=1792,
    )
    assert diag["dimensions_valid"] is True
    assert diag["quality_validated"] is True
    assert "color_coherence_score" in diag
    assert diag["color_coherence_score"] >= 0.8


# -----------------------------------------------------------------------------
# 8-20: Full Pipeline Integration & Endpoint Tests
# -----------------------------------------------------------------------------

def test_full_consistency_pipeline_and_endpoints(tmp_path: Path):
    """
    End-to-end integration test:
    1. Create Project
    2. Upload Video
    3. Analyze Video (Phase 7)
    4. Vision Analysis (Phase 8)
    5. Phase 9 Initial Comic Generation
    6. Fetch / Create Character Consistency Profile
    7. Generate Reference-Guided Consistent Comic Frames (Sequential Batch)
    8. Verify Temporal Chaining (previous_frame_id linking)
    9. Verify Media Storage Persistence & File Retrieval
    10. Regenerate Single Frame
    11. Verify Project Retrieval API with Consistency Metadata
    """
    # 1. Create Project
    create_res = client.post("/api/v1/projects", json={"name": "Consistency Pipeline Test"})
    assert create_res.status_code == 201
    project_id = create_res.json()["project"]["id"]

    # 2. Upload synthetic video with 2 seconds (multiscene detection)
    video_path = tmp_path / "consistency_video.mp4"
    create_synthetic_test_video(video_path, duration=2.5)

    with open(video_path, "rb") as f:
        up_res = client.post(
            f"/api/v1/projects/{project_id}/media",
            data={"media_type": "source_video"},
            files={"file": ("consistency_video.mp4", f.read(), "video/mp4")},
        )
    assert up_res.status_code == 201
    media_id = up_res.json()["media"]["id"]

    # 3. Analyze Video (Phase 7)
    ana_res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert ana_res.status_code == 200
    scenes = ana_res.json()["analysis"]["scenes"]
    assert len(scenes) >= 1
    scene_1_id = scenes[0]["id"]

    # 4. Vision Analysis (Phase 8)
    vis_res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/vision-analysis")
    assert vis_res.status_code == 200

    # 5. Phase 9 Comic Generation (Initial Direct)
    with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
        p9_res = client.post(
            f"/api/v1/projects/{project_id}/comic-generation",
            json={"style_preset": "3d-comic"},
        )
        assert p9_res.status_code == 200
        p9_gen = p9_res.json()["generation"]
        assert len(p9_gen["frames"]) >= 1

    # 6. Fetch / Create Character Consistency Profile (POST /consistency/profile)
    prof_res = client.post(
        f"/api/v1/projects/{project_id}/consistency/profile",
        json={"style_preset": "v1-3d-comic-lock"},
    )
    assert prof_res.status_code == 200
    prof_data = prof_res.json()["profile"]
    assert prof_data["project_id"] == project_id
    assert prof_data["canonical_reference_id"] is not None
    assert prof_data["descriptor_metadata"] is not None
    assert prof_data["style_version"] == "v1-3d-comic-lock"

    # 7. Generate Reference-Guided Consistent Comic Frames (POST /consistency/generate)
    with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
        gen_res = client.post(
            f"/api/v1/projects/{project_id}/consistency/generate",
            json={
                "style_preset": "v1-3d-comic-lock",
                "prompt_directive": "Maintain cinematic comic ink contours and jacket color",
            },
        )
        assert gen_res.status_code == 200
        cons_data = gen_res.json()["generation"]
        assert cons_data["status"] == "completed"
        assert cons_data["provider"] == "mock"
        assert len(cons_data["frames"]) >= 1

        frames = cons_data["frames"]

        # 8. Verify Sequential Temporal Chaining (previous_frame_id)
        # First frame should have previous_frame_id = None
        assert frames[0]["previous_frame_id"] is None
        assert frames[0]["sequence"] == 0

        if len(frames) > 1:
            # Subsequent frame must point to previous frame's ID
            assert frames[1]["previous_frame_id"] == frames[0]["id"]
            assert frames[1]["sequence"] == 1

        # 9. Verify Media Storage Persistence & File Retrieval
        for frame in frames:
            assert frame["output_media_file_id"] is not None
            assert frame["status"] == "completed"
            assert frame["width"] == 1024
            assert frame["height"] == 1792

            out_media_id = frame["output_media_file_id"]
            file_res = client.get(f"/api/v1/projects/{project_id}/media/{out_media_id}/file")
            assert file_res.status_code == 200
            assert file_res.headers["content-type"] == "image/png"
            assert len(file_res.content) > 0

        # 10. Regenerate Single Frame
        regen_res = client.post(
            f"/api/v1/projects/{project_id}/consistency/generate",
            json={
                "scene_id": scene_1_id,
                "style_preset": "v1-3d-comic-lock",
            },
        )
        assert regen_res.status_code == 200
        regen_data = regen_res.json()["generation"]
        assert len(regen_data["frames"]) == 1
        assert regen_data["frames"][0]["scene_id"] == scene_1_id

    # 11. Verify Project Retrieval API with Consistency Metadata (GET /projects/{id})
    proj_res = client.get(f"/api/v1/projects/{project_id}")
    assert proj_res.status_code == 200
    p_json = proj_res.json()["project"]
    assert "consistency_profiles" in p_json
    assert len(p_json["consistency_profiles"]) >= 1
    assert "consistency_generations" in p_json
    assert len(p_json["consistency_generations"]) >= 2  # batch + single regen


def test_consistency_api_invalid_project_404():
    """Verify 404 for non-existent project in consistency endpoints."""
    res = client.post("/api/v1/projects/PROJ-NONEXISTENT/consistency/generate", json={})
    assert res.status_code == 404
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code in ("PROJECT_NOT_FOUND", "NOT_FOUND")


def test_consistency_api_missing_scene_analysis_400():
    """Verify 400 when Phase 7 video scene analysis is missing."""
    create_res = client.post("/api/v1/projects", json={"name": "No Analysis Project"})
    pid = create_res.json()["project"]["id"]

    res = client.post(f"/api/v1/projects/{pid}/consistency/generate", json={})
    assert res.status_code == 400
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code == "MISSING_SCENE_ANALYSIS"


def test_consistency_api_nonexistent_scene_404(tmp_path: Path):
    """Verify 404 when requested scene_id does not exist."""
    create_res = client.post("/api/v1/projects", json={"name": "Scene 404 Project"})
    pid = create_res.json()["project"]["id"]

    video_path = tmp_path / "test_404.mp4"
    create_synthetic_test_video(video_path, duration=1.0)

    with open(video_path, "rb") as f:
        up_res = client.post(
            f"/api/v1/projects/{pid}/media",
            data={"media_type": "source_video"},
            files={"file": ("test_404.mp4", f.read(), "video/mp4")},
        )
    mid = up_res.json()["media"]["id"]

    # Run scene analysis & vision analysis
    client.post(f"/api/v1/projects/{pid}/media/{mid}/analyze")
    client.post(f"/api/v1/projects/{pid}/media/{mid}/vision-analysis")

    res = client.post(
        f"/api/v1/projects/{pid}/consistency/generate",
        json={"scene_id": "nonexistent-scene-uuid"},
    )
    assert res.status_code == 404
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code == "SCENE_NOT_FOUND"


def test_openai_consistency_provider_mocked_image_generation():
    """Verify OpenAI provider can be used for consistency generation with mocked API."""
    mock_client = MagicMock()

    buf = io.BytesIO()
    Image.new("RGB", (1024, 1792), color=(40, 50, 60)).save(buf, format="PNG")
    dummy_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    mock_item = MagicMock()
    mock_item.b64_json = dummy_b64
    mock_item.url = None

    mock_resp = MagicMock()
    mock_resp.data = [mock_item]
    mock_client.images.generate.return_value = mock_resp

    provider = OpenAIComicProvider(api_key="sk-test-consistency", openai_client=mock_client)
    img_bytes, w, h = provider.generate_comic_frame(
        prompt="Consistent character scene 1",
        width=1024,
        height=1792,
    )
    assert len(img_bytes) == len(buf.getvalue())
    assert w == 1024
    assert h == 1792
