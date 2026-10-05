"""
3D Reel Studio — Final Video Compositing & 9:16 Reel Rendering Tests
Phase 13: Final Video Compositing + 9:16 Reel Rendering
"""

import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import SessionLocal, init_db
from app.models.project import (
    Project,
    MediaFile,
    VideoAnalysis,
    VideoScene,
    SceneKeyframe,
    ConsistentComicFrame,
    SegmentationResult,
    LyricStyle,
    LyricAnimation,
    LyricSegment,
    RenderJob,
    generate_uuid,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir
from app.services.audio import resolve_ffmpeg_path
from app.services.render import (
    ReelCompositingEngine,
    resize_and_fit_916,
    run_final_reel_render_sync,
    cancel_render_job,
)

from tests.conftest import get_test_auth_headers

client = TestClient(app, headers=get_test_auth_headers())


@pytest.fixture(scope="module", autouse=True)
def ensure_db_schema():
    """Initializes the database schema including the new render_jobs table."""
    init_db()


@pytest.fixture
def db_session():
    """Provides a fresh database session for each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_mock_mp4_video(file_path: Path, duration_sec: int = 2, width: int = 1080, height: int = 1920) -> None:
    """Generates a small valid MP4 test video using FFmpeg."""
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        # Fallback dummy binary file
        file_path.write_bytes(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41")
        return

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:d={duration_sec}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=stereo:d={duration_sec}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(file_path),
    ]
    subprocess.run(cmd, capture_output=True, check=False)


def create_mock_mp3_audio(file_path: Path, duration_sec: int = 2) -> None:
    """Generates a small valid MP3 test audio file using FFmpeg."""
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        file_path.write_bytes(b"\xff\xfb\x90\x64\x00\x00\x00\x00")
        return

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_sec}",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(file_path),
    ]
    subprocess.run(cmd, capture_output=True, check=False)


@pytest.fixture
def setup_render_project(db_session: Session):
    """Sets up a complete project with video, scene, segmentation layers, audio, and lyrics."""
    proj_id = f"PROJ-RND-{generate_uuid()[:8].upper()}"
    project = Project(id=proj_id, name="Test Render Project", status="draft")
    db_session.add(project)
    db_session.commit()

    # 1. Source Video
    src_dir = get_project_storage_dir(proj_id, "source_video")
    src_path = src_dir / f"{proj_id}_source.mp4"
    create_mock_mp4_video(src_path, duration_sec=2)

    source_mf = MediaFile(
        project_id=proj_id,
        file_type="source_video",
        original_filename="source.mp4",
        stored_filename=src_path.name,
        file_path=str(src_path),
        mime_type="video/mp4",
        file_size=src_path.stat().st_size if src_path.is_file() else 1024,
    )
    db_session.add(source_mf)
    db_session.flush()

    # 2. Extracted Audio
    aud_dir = get_project_storage_dir(proj_id, "extracted_audio")
    aud_path = aud_dir / f"{proj_id}_audio.mp3"
    create_mock_mp3_audio(aud_path, duration_sec=2)

    audio_mf = MediaFile(
        project_id=proj_id,
        file_type="extracted_audio",
        original_filename="audio.mp3",
        stored_filename=aud_path.name,
        file_path=str(aud_path),
        mime_type="audio/mpeg",
        file_size=aud_path.stat().st_size if aud_path.is_file() else 512,
    )
    db_session.add(audio_mf)
    db_session.flush()

    # 3. Video Analysis & Scene
    v_analysis = VideoAnalysis(
        id=f"va-{generate_uuid()[:8]}",
        project_id=proj_id,
        source_media_id=source_mf.id,
        width=1080,
        height=1920,
        fps=30.0,
        duration=2.0,
        frame_count=60,
        aspect_ratio="9:16",
    )
    db_session.add(v_analysis)
    db_session.flush()

    scene = VideoScene(
        id=f"scene-{generate_uuid()[:8]}",
        analysis_id=v_analysis.id,
        sequence=0,
        start_time=0.0,
        end_time=2.0,
        duration=2.0,
    )
    db_session.add(scene)
    db_session.flush()

    # 4. Keyframe Image
    kf_dir = get_project_storage_dir(proj_id, "keyframe_image")
    kf_path = kf_dir / f"{proj_id}_kf_0.jpg"
    img = Image.new("RGB", (1080, 1920), color=(30, 40, 60))
    img.save(kf_path, format="JPEG")

    kf_mf = MediaFile(
        project_id=proj_id,
        file_type="keyframe_image",
        original_filename="kf_0.jpg",
        stored_filename=kf_path.name,
        file_path=str(kf_path),
        mime_type="image/jpeg",
        file_size=kf_path.stat().st_size,
    )
    db_session.add(kf_mf)
    db_session.flush()

    kf = SceneKeyframe(
        id=f"kf-{generate_uuid()[:8]}",
        scene_id=scene.id,
        timestamp=1.0,
        media_file_id=kf_mf.id,
        width=1080,
        height=1920,
    )
    db_session.add(kf)

    # 5. Phase 11 Segmentation Layers (Background + Foreground RGBA)
    bg_dir = get_project_storage_dir(proj_id, "segmentation_background")
    bg_path = bg_dir / f"{proj_id}_bg_0.png"
    bg_img = Image.new("RGBA", (1080, 1920), color=(20, 30, 50, 255))
    bg_img.save(bg_path, format="PNG")

    bg_mf = MediaFile(
        project_id=proj_id,
        file_type="segmentation_background",
        original_filename="bg.png",
        stored_filename=bg_path.name,
        file_path=str(bg_path),
        mime_type="image/png",
        file_size=bg_path.stat().st_size,
    )
    db_session.add(bg_mf)

    fg_dir = get_project_storage_dir(proj_id, "segmentation_foreground")
    fg_path = fg_dir / f"{proj_id}_fg_0.png"
    fg_img = Image.new("RGBA", (1080, 1920), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(fg_img)
    draw.rectangle([300, 400, 780, 1600], fill=(255, 100, 100, 255))
    fg_img.save(fg_path, format="PNG")

    fg_mf = MediaFile(
        project_id=proj_id,
        file_type="segmentation_foreground",
        original_filename="fg.png",
        stored_filename=fg_path.name,
        file_path=str(fg_path),
        mime_type="image/png",
        file_size=fg_path.stat().st_size,
    )
    db_session.add(fg_mf)

    comp_dir = get_project_storage_dir(proj_id, "segmentation_composite")
    comp_path = comp_dir / f"{proj_id}_comp_0.png"
    comp_img = Image.alpha_composite(bg_img, fg_img)
    comp_img.save(comp_path, format="PNG")

    comp_mf = MediaFile(
        project_id=proj_id,
        file_type="segmentation_composite",
        original_filename="comp.png",
        stored_filename=comp_path.name,
        file_path=str(comp_path),
        mime_type="image/png",
        file_size=comp_path.stat().st_size,
    )
    db_session.add(comp_mf)

    seg_res = SegmentationResult(
        project_id=proj_id,
        source_scene_id=scene.id,
        status="completed",
        background_mode="ORIGINAL",
        background_media_file_id=bg_mf.id,
        foreground_media_file_id=fg_mf.id,
        composite_media_file_id=comp_mf.id,
    )
    db_session.add(seg_res)

    # 6. Phase 12 Lyric Style, Animation, and Segment
    style = LyricStyle(
        project_id=proj_id,
        name="STYLE_01_BOLD_CINEMATIC",
        font_family="Arial",
        font_size=72,
        fill_color="#FFFFFF",
        outline_color="#000000",
        outline_width=8,
    )
    db_session.add(style)

    anim = LyricAnimation(
        project_id=proj_id,
        name="POP",
        animation_type="POP",
        duration=0.4,
        easing="back_out",
    )
    db_session.add(anim)
    db_session.flush()

    lyric_seg = LyricSegment(
        project_id=proj_id,
        style_id=style.id,
        animation_id=anim.id,
        sequence=0,
        start_time=0.2,
        end_time=1.8,
        text="NEVER GIVE UP",
        position_x=0.5,
        position_y=0.75,
        scale=1.0,
        opacity=1.0,
        enabled=True,
    )
    db_session.add(lyric_seg)

    db_session.commit()

    return {
        "project_id": proj_id,
        "source_media": source_mf,
        "scene": scene,
        "seg_res": seg_res,
        "lyric_seg": lyric_seg,
    }


def test_resize_and_fit_916():
    """Tests fitting arbitrary resolution images to 1080x1920 (9:16) without distortion."""
    # 1. Square image (1000x1000)
    sq = Image.new("RGBA", (1000, 1000), color=(255, 0, 0, 255))
    fitted_sq = resize_and_fit_916(sq, target_width=1080, target_height=1920)
    assert fitted_sq.width == 1080
    assert fitted_sq.height == 1920

    # 2. Horizontal image (1920x1080)
    horiz = Image.new("RGBA", (1920, 1080), color=(0, 255, 0, 255))
    fitted_h = resize_and_fit_916(horiz, target_width=1080, target_height=1920)
    assert fitted_h.width == 1080
    assert fitted_h.height == 1920

    # 3. Exactly 9:16 (1024x1792)
    exact_ratio = Image.new("RGBA", (1024, 1792), color=(0, 0, 255, 255))
    fitted_e = resize_and_fit_916(exact_ratio, target_width=1080, target_height=1920)
    assert fitted_e.width == 1080
    assert fitted_e.height == 1920


def test_render_job_creation_and_sync_execution(db_session: Session, setup_render_project: dict):
    """Tests synchronous render pipeline execution producing a valid 9:16 MP4 reel."""
    proj_id = setup_render_project["project_id"]
    source_mf = setup_render_project["source_media"]

    job = RenderJob(
        project_id=proj_id,
        source_media_id=source_mf.id,
        status="queued",
        width=1080,
        height=1920,
        fps=30.0,
        video_codec="libx264",
        audio_codec="aac",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    completed_job = run_final_reel_render_sync(
        db=db_session,
        project_id=proj_id,
        job_id=job.id,
        output_width=1080,
        output_height=1920,
        fps=30.0,
        include_audio=True,
        include_lyrics=True,
    )

    assert completed_job.status == "completed"
    assert completed_job.progress == 1.0
    assert completed_job.output_media_file_id is not None
    assert completed_job.duration is not None
    assert completed_job.completed_at is not None

    # Verify MediaFile created
    out_mf = db_session.query(MediaFile).filter(MediaFile.id == completed_job.output_media_file_id).first()
    assert out_mf is not None
    assert out_mf.file_type == "final_reel"
    assert out_mf.mime_type == "video/mp4"
    assert Path(out_mf.file_path).is_file()
    assert out_mf.file_size > 0
    assert len(out_mf.sha256_hash) == 64


def test_render_api_endpoint_success(setup_render_project: dict):
    """Tests POST /api/v1/projects/{project_id}/render endpoint."""
    proj_id = setup_render_project["project_id"]

    res = client.post(
        f"/api/v1/projects/{proj_id}/render",
        json={
            "output_width": 1080,
            "output_height": 1920,
            "fps": 30.0,
            "video_codec": "libx264",
            "audio_codec": "aac",
            "include_audio": True,
            "include_lyrics": True,
            "force_rerender": True,
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    job = data["job"]
    assert job["project_id"] == proj_id
    assert job["status"] == "completed"
    assert job["width"] == 1080
    assert job["height"] == 1920
    assert job["output_media_file_id"] is not None


def test_list_and_get_render_jobs_api(setup_render_project: dict):
    """Tests GET /api/v1/projects/{project_id}/render and GET /render/{render_id}."""
    proj_id = setup_render_project["project_id"]

    # Trigger a render first
    res_post = client.post(f"/api/v1/projects/{proj_id}/render", json={})
    assert res_post.status_code == 200

    # 1. List render jobs
    res_list = client.get(f"/api/v1/projects/{proj_id}/render")
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["success"] is True
    assert data["count"] >= 1
    assert data["latest_render"] is not None

    render_id = data["latest_render"]["id"]

    # 2. Get specific render job
    res_get = client.get(f"/api/v1/projects/{proj_id}/render/{render_id}")
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["success"] is True
    assert get_data["job"]["id"] == render_id


def test_cancel_render_job_api(db_session: Session, setup_render_project: dict):
    """Tests POST /api/v1/projects/{project_id}/render/{render_id}/cancel."""
    proj_id = setup_render_project["project_id"]
    source_mf = setup_render_project["source_media"]

    job = RenderJob(
        project_id=proj_id,
        source_media_id=source_mf.id,
        status="queued",
        width=1080,
        height=1920,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    res = client.post(f"/api/v1/projects/{proj_id}/render/{job.id}/cancel")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["job"]["status"] == "cancelled"


def test_render_idempotency(setup_render_project: dict):
    """Tests that repeat requests return existing completed job unless force_rerender is set."""
    proj_id = setup_render_project["project_id"]

    # First request
    res1 = client.post(f"/api/v1/projects/{proj_id}/render", json={"force_rerender": False})
    assert res1.status_code == 200
    job1_id = res1.json()["job"]["id"]

    # Second request without force_rerender
    res2 = client.post(f"/api/v1/projects/{proj_id}/render", json={"force_rerender": False})
    assert res2.status_code == 200
    job2_id = res2.json()["job"]["id"]

    assert job1_id == job2_id


def test_render_missing_source_video_rejection(db_session: Session):
    """Tests 400 rejection when trying to render without a source video."""
    proj_id = f"PROJ-EMPTY-{generate_uuid()[:8].upper()}"
    proj = Project(id=proj_id, name="Empty Project")
    db_session.add(proj)
    db_session.commit()

    res = client.post(f"/api/v1/projects/{proj_id}/render", json={})
    assert res.status_code == 400
    data = res.json()
    assert "SOURCE_VIDEO_MISSING" in str(data)


def test_render_invalid_project_404():
    """Tests 404 rejection when project does not exist."""
    res = client.post("/api/v1/projects/PROJ-NONEXISTENT-9999/render", json={})
    assert res.status_code == 404


def test_render_project_retrieval_includes_render_jobs(setup_render_project: dict):
    """Tests that GET /api/v1/projects/{project_id} includes render_jobs."""
    proj_id = setup_render_project["project_id"]

    # Trigger a render first
    render_res = client.post(f"/api/v1/projects/{proj_id}/render", json={})
    assert render_res.status_code == 200

    res = client.get(f"/api/v1/projects/{proj_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "render_jobs" in data["project"]
    assert len(data["project"]["render_jobs"]) >= 1
