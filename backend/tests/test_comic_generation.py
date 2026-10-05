"""
3D Reel Studio — 3D Comic Style Generation Tests
Phase 9: 3D Comic Style Generation
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
from app.services.comic_generation import (
    ComicGenerationProvider,
    MockComicProvider,
    OpenAIComicProvider,
    build_comic_generation_prompt,
    get_comic_generation_provider,
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

        # Draw a face (skin ellipse in BGR format: YCbCr/HSV skin tones)
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
# Unit Tests: Prompt Building & Providers
# -----------------------------------------------------------------------------

def test_build_comic_generation_prompt():
    """Verify prompt builder creates structured prompts for styles and overrides."""
    # Default 3d-comic
    prompt, version = build_comic_generation_prompt(
        style_preset="3d-comic",
        primary_subject_info={"is_primary": True, "confidence": 0.95},
        face_reference_present=True,
        scene_sequence=1,
    )
    assert "3D comic" in prompt or "3d-comic" in version
    assert "v1-3d-comic" == version
    assert "Avoid: distorted anatomy" in prompt

    # Cyber-hero preset
    prompt_ch, ver_ch = build_comic_generation_prompt(style_preset="cyber-hero")
    assert "cyberpunk" in prompt_ch.lower()
    assert "v1-cyber-hero" == ver_ch

    # Prompt override
    prompt_ov, ver_ov = build_comic_generation_prompt(
        style_preset="3d-comic",
        prompt_override="Spider-man jumping over neon skyscraper at sunset",
    )
    assert "Spider-man jumping over neon skyscraper" in prompt_ov
    assert "9:16 vertical reel" in prompt_ov


def test_mock_comic_provider_generation(tmp_path: Path):
    """Verify MockComicProvider generates valid 9:16 image bytes."""
    provider = MockComicProvider()
    assert provider.provider_name == "mock"
    assert "mock" in provider.model_name

    # Create dummy keyframe
    kf_path = tmp_path / "dummy_kf.png"
    Image.new("RGB", (320, 568), color=(50, 100, 150)).save(kf_path)

    img_bytes, width, height = provider.generate_comic_frame(
        prompt="Test comic prompt",
        keyframe_path=kf_path,
        width=1024,
        height=1792,
    )
    assert len(img_bytes) > 0
    assert width == 1024
    assert height == 1792

    # Verify image opens with PIL and matches dimensions
    with Image.open(io.BytesIO(img_bytes)) as parsed:
        assert parsed.size == (1024, 1792)


def test_openai_comic_provider_missing_api_key():
    """Verify OpenAI provider raises 400 when API key is missing."""
    with patch.object(settings, "OPENAI_API_KEY", None), patch.object(settings, "COMIC_GENERATION_API_KEY", None):
        provider = OpenAIComicProvider(api_key="")
        with pytest.raises(Exception) as exc_info:
            provider.generate_comic_frame("A comic hero")
        assert "MISSING_COMIC_API_KEY" in str(exc_info.value)


def test_openai_comic_provider_successful_mocked_generation():
    """Verify OpenAI provider parses b64_json response from Images API."""
    mock_client = MagicMock()

    # Generate small dummy PNG base64
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1792), color=(20, 30, 40)).save(buf, format="PNG")
    dummy_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    mock_item = MagicMock()
    mock_item.b64_json = dummy_b64
    mock_item.url = None

    mock_resp = MagicMock()
    mock_resp.data = [mock_item]
    mock_client.images.generate.return_value = mock_resp

    provider = OpenAIComicProvider(api_key="sk-test-key", openai_client=mock_client)
    img_bytes, w, h = provider.generate_comic_frame(
        prompt="Hero in cyberpunk city",
        width=1024,
        height=1792,
    )
    assert len(img_bytes) == len(buf.getvalue())
    assert w == 1024
    assert h == 1792
    mock_client.images.generate.assert_called_once()


def test_openai_comic_provider_auth_error_handling():
    """Verify OpenAI authentication errors return HTTP 401."""
    from openai import AuthenticationError

    mock_client = MagicMock()
    mock_client.images.generate.side_effect = AuthenticationError(
        message="Invalid API key",
        response=MagicMock(status_code=401),
        body=None,
    )

    provider = OpenAIComicProvider(api_key="sk-invalid", openai_client=mock_client)
    with pytest.raises(Exception) as exc_info:
        provider.generate_comic_frame("Comic scene")
    assert "OPENAI_AUTH_ERROR" in str(exc_info.value)


def test_openai_comic_provider_rate_limit_handling():
    """Verify OpenAI rate limit errors return HTTP 429."""
    from openai import RateLimitError

    mock_client = MagicMock()
    mock_client.images.generate.side_effect = RateLimitError(
        message="Rate limit exceeded",
        response=MagicMock(status_code=429),
        body=None,
    )

    provider = OpenAIComicProvider(api_key="sk-test", openai_client=mock_client)
    with pytest.raises(Exception) as exc_info:
        provider.generate_comic_frame("Comic scene")
    assert "OPENAI_RATE_LIMIT" in str(exc_info.value)


def test_openai_comic_provider_connection_error_handling():
    """Verify OpenAI network connection errors return HTTP 502."""
    from openai import APIConnectionError

    mock_client = MagicMock()
    mock_client.images.generate.side_effect = APIConnectionError(
        request=MagicMock()
    )

    provider = OpenAIComicProvider(api_key="sk-test", openai_client=mock_client)
    with pytest.raises(Exception) as exc_info:
        provider.generate_comic_frame("Comic scene")
    assert "OPENAI_CONNECTION_ERROR" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Integration Tests: POST /api/v1/projects/{project_id}/comic-generation
# -----------------------------------------------------------------------------

def test_comic_generation_api_single_and_batch_success(tmp_path: Path):
    """Test full pipeline: create project -> upload real video -> analyze video -> vision analysis -> comic generation."""
    # 1. Create Project
    create_res = client.post("/api/v1/projects", json={"name": "Comic Test Reel"})
    assert create_res.status_code == 201
    project_id = create_res.json()["project"]["id"]

    # 2. Create and Upload synthetic video
    video_path = tmp_path / "test_video.mp4"
    create_synthetic_test_video(video_path, duration=2.0)

    with open(video_path, "rb") as f:
        upload_res = client.post(
            f"/api/v1/projects/{project_id}/media",
            data={"media_type": "source_video"},
            files={"file": ("test_video.mp4", f.read(), "video/mp4")},
        )
    assert upload_res.status_code == 201
    media_id = upload_res.json()["media"]["id"]

    # 3. Analyze Video (Phase 7)
    v_res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/analyze")
    assert v_res.status_code == 200
    analysis_data = v_res.json()["analysis"]
    assert len(analysis_data["scenes"]) >= 1
    scene_1_id = analysis_data["scenes"][0]["id"]

    # 4. Vision Analysis (Phase 8)
    vis_res = client.post(f"/api/v1/projects/{project_id}/media/{media_id}/vision-analysis")
    assert vis_res.status_code == 200

    # 5. Generate 3D Comic Frame for Single Scene using Mock Provider
    with patch.object(settings, "COMIC_GENERATION_PROVIDER", "mock"):
        comic_res = client.post(
            f"/api/v1/projects/{project_id}/comic-generation",
            json={
                "scene_id": scene_1_id,
                "style_preset": "3d-comic",
            },
        )
        assert comic_res.status_code == 200
        gen_data = comic_res.json()["generation"]
        assert gen_data["status"] == "completed"
        assert gen_data["provider"] == "mock"
        assert len(gen_data["frames"]) == 1

        frame = gen_data["frames"][0]
        assert frame["status"] == "completed"
        assert frame["scene_id"] == scene_1_id
        assert frame["output_media_file_id"] is not None
        assert frame["width"] == 1024
        assert frame["height"] == 1792

        # 6. Verify Generated Media File Can Be Retrieved
        out_media_id = frame["output_media_file_id"]
        file_res = client.get(f"/api/v1/projects/{project_id}/media/{out_media_id}/file")
        assert file_res.status_code == 200
        assert file_res.headers["content-type"] == "image/png"
        assert len(file_res.content) > 0

        # 7. Batch Generate for All Scenes
        batch_res = client.post(
            f"/api/v1/projects/{project_id}/comic-generation",
            json={
                "style_preset": "cyber-hero",
            },
        )
        assert batch_res.status_code == 200
        batch_data = batch_res.json()["generation"]
        assert batch_data["status"] == "completed"
        assert len(batch_data["frames"]) >= 1

    # 8. Verify Project Retrieval includes comic generations
    proj_detail_res = client.get(f"/api/v1/projects/{project_id}")
    assert proj_detail_res.status_code == 200
    p_data = proj_detail_res.json()["project"]
    assert "comic_generations" in p_data
    assert len(p_data["comic_generations"]) >= 2


def test_comic_generation_api_invalid_project_404():
    """Verify 404 for non-existent project."""
    res = client.post("/api/v1/projects/PROJ-NONEXIST/comic-generation", json={})
    assert res.status_code == 404
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code in ("PROJECT_NOT_FOUND", "NOT_FOUND")


def test_comic_generation_api_missing_scene_analysis_400():
    """Verify 400 when Phase 7 video scene analysis has not been performed."""
    create_res = client.post("/api/v1/projects", json={"name": "No Analysis Project"})
    pid = create_res.json()["project"]["id"]

    res = client.post(f"/api/v1/projects/{pid}/comic-generation", json={})
    assert res.status_code == 400
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code == "MISSING_SCENE_ANALYSIS"


def test_comic_generation_api_nonexistent_scene_404(tmp_path: Path):
    """Verify 404 when requested scene_id does not exist."""
    # Create project & upload
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

    # Run scene analysis
    client.post(f"/api/v1/projects/{pid}/media/{mid}/analyze")

    res = client.post(
        f"/api/v1/projects/{pid}/comic-generation",
        json={"scene_id": "nonexistent-scene-uuid"},
    )
    assert res.status_code == 404
    data = res.json()
    code = data.get("error", {}).get("code") if "error" in data else data.get("detail", {}).get("code")
    assert code == "SCENE_NOT_FOUND"


def test_comic_generation_unsupported_provider_400():
    """Verify error when invalid provider is configured."""
    with pytest.raises(Exception) as exc:
        get_comic_generation_provider(provider_name="unsupported-provider-xyz")
    assert "UNSUPPORTED_PROVIDER" in str(exc.value)
