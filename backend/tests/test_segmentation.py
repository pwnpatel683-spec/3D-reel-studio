"""
3D Reel Studio — Tests for Foreground Segmentation & Dynamic Background Layering
Phase 11: Foreground Segmentation + Dynamic Background
"""

import io
import uuid
import numpy as np
import pytest
from PIL import Image
from starlette.testclient import TestClient
from tests.conftest import get_test_auth_headers

from app.core.config import settings
from app.db.session import SessionLocal, get_db, init_db
from app.main import app
from app.models.project import (
    ComicFrame,
    ComicGeneration,
    ConsistencyGeneration,
    ConsistentComicFrame,
    MediaFile,
    Project,
    SceneKeyframe,
    SegmentationResult,
    VideoAnalysis,
    VideoScene,
    VisionAnalysis,
    DetectedSubject,
    FaceDetection,
    PoseDetection,
    PoseLandmark,
)
from app.services.segmentation import (
    ForegroundSegmentationProvider,
    MockSegmentationProvider,
    OpenCVSubjectGuidedSegmentationProvider,
    apply_background_mode,
    generate_composite_image,
    get_segmentation_provider,
    reconstruct_clean_background,
    refine_mask,
    run_segmentation_pipeline,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir

# Ensure tables are created
init_db()


@pytest.fixture
def db_session():
    """Yields a database session and ensures cleanup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_project_with_consistent_frame(db_session):
    """
    Creates a full deterministic database fixture with Project, VideoAnalysis,
    SceneKeyframe, ComicFrame, and ConsistentComicFrame with real image files on disk.
    """
    project_id = f"PROJ-TEST-{uuid.uuid4().hex[:6].upper()}"
    project = Project(id=project_id, name="Test Segmentation Reel", status="draft")
    db_session.add(project)

    # 1. Source Video Media
    video_media = MediaFile(
        id=str(uuid.uuid4()),
        project_id=project_id,
        file_type="source_video",
        original_filename="sample.mp4",
        stored_filename=f"{uuid.uuid4().hex}.mp4",
        file_path=f"projects/{project_id}/source/sample.mp4",
        mime_type="video/mp4",
        file_size=1024 * 100,
    )
    db_session.add(video_media)

    # 2. Keyframe Media & Image
    kf_dir = get_project_storage_dir(project_id, "keyframe_image")
    kf_filename = f"kf_{uuid.uuid4().hex}.jpg"
    kf_path = kf_dir / kf_filename
    
    # Create synthetic keyframe RGB image (100x160)
    kf_img = np.zeros((160, 100, 3), dtype=np.uint8)
    kf_img[:, :] = [120, 140, 160]  # Background tone
    Image.fromarray(kf_img).save(kf_path, format="JPEG")

    kf_media = MediaFile(
        id=str(uuid.uuid4()),
        project_id=project_id,
        file_type="keyframe_image",
        original_filename="keyframe_0.jpg",
        stored_filename=kf_filename,
        file_path=str(kf_path.relative_to(get_base_storage_dir())).replace("\\", "/"),
        mime_type="image/jpeg",
        file_size=len(kf_path.read_bytes()),
    )
    db_session.add(kf_media)

    # 3. Video Analysis & Scene
    v_analysis = VideoAnalysis(
        id=str(uuid.uuid4()),
        project_id=project_id,
        source_media_id=video_media.id,
        width=100,
        height=160,
        fps=30.0,
        frame_count=150,
        duration=5.0,
        aspect_ratio="9:16",
    )
    db_session.add(v_analysis)

    scene = VideoScene(
        id=str(uuid.uuid4()),
        analysis_id=v_analysis.id,
        sequence=0,
        start_time=0.0,
        end_time=5.0,
        duration=5.0,
    )
    db_session.add(scene)

    keyframe = SceneKeyframe(
        id=str(uuid.uuid4()),
        scene_id=scene.id,
        timestamp=1.0,
        media_file_id=kf_media.id,
        width=100,
        height=160,
    )
    db_session.add(keyframe)

    # 4. Vision Analysis with Face & Pose
    vis_analysis = VisionAnalysis(
        id=str(uuid.uuid4()),
        project_id=project_id,
        source_media_id=video_media.id,
        primary_subject_id=None,
        faces_detected_count=1,
        pose_frames_count=1,
    )
    db_session.add(vis_analysis)

    subject = DetectedSubject(
        id=str(uuid.uuid4()),
        analysis_id=vis_analysis.id,
        sequence=0,
        is_primary=True,
        confidence=0.98,
    )
    db_session.add(subject)

    face = FaceDetection(
        id=str(uuid.uuid4()),
        subject_id=subject.id,
        timestamp=1.0,
        x=0.30,
        y=0.15,
        width=0.40,
        height=0.30,
        confidence=0.95,
    )
    db_session.add(face)

    pose = PoseDetection(
        id=str(uuid.uuid4()),
        subject_id=subject.id,
        timestamp=1.0,
        confidence=0.95,
    )
    db_session.add(pose)

    for idx, (lx, ly) in enumerate([(0.5, 0.2), (0.4, 0.4), (0.6, 0.4), (0.5, 0.7)]):
        lm = PoseLandmark(
            id=str(uuid.uuid4()),
            pose_detection_id=pose.id,
            landmark_index=idx,
            landmark_name=f"pt_{idx}",
            x=lx,
            y=ly,
            z=0.0,
            visibility=0.9,
        )
        db_session.add(lm)

    # 5. Consistent Comic Frame Media & Image
    c_dir = get_project_storage_dir(project_id, "consistent_comic_frame")
    c_filename = f"consistent_{uuid.uuid4().hex}.jpg"
    c_path = c_dir / c_filename

    # Create synthetic comic frame with bright subject in center
    comic_img = np.full((160, 100, 3), 40, dtype=np.uint8)  # Dark background
    # Draw character figure (white/bright)
    comic_img[30:130, 25:75] = [220, 180, 140]  # Torso/legs
    comic_img[20:50, 35:65] = [240, 200, 160]   # Face
    Image.fromarray(comic_img).save(c_path, format="JPEG")

    c_media = MediaFile(
        id=str(uuid.uuid4()),
        project_id=project_id,
        file_type="consistent_comic_frame",
        original_filename="consistent_frame_0.jpg",
        stored_filename=c_filename,
        file_path=str(c_path.relative_to(get_base_storage_dir())).replace("\\", "/"),
        mime_type="image/jpeg",
        file_size=len(c_path.read_bytes()),
    )
    db_session.add(c_media)

    c_gen = ConsistencyGeneration(
        id=str(uuid.uuid4()),
        project_id=project_id,
        provider="openai",
        model="dall-e-3",
        status="completed",
    )
    db_session.add(c_gen)

    consistent_frame = ConsistentComicFrame(
        id=str(uuid.uuid4()),
        consistency_generation_id=c_gen.id,
        scene_id=scene.id,
        output_media_file_id=c_media.id,
        sequence=0,
        timestamp=1.0,
        width=100,
        height=160,
        status="completed",
    )
    db_session.add(consistent_frame)
    db_session.commit()

    return {
        "project_id": project_id,
        "consistent_frame_id": consistent_frame.id,
        "scene_id": scene.id,
        "consistent_frame_path": c_path,
        "keyframe_path": kf_path,
    }


def test_segmentation_provider_factory():
    """Validates factory correctly instantiates providers."""
    p_opencv = get_segmentation_provider("opencv_guided")
    assert isinstance(p_opencv, OpenCVSubjectGuidedSegmentationProvider)
    assert p_opencv.provider_name == "opencv_guided"

    p_mock = get_segmentation_provider("mock")
    assert isinstance(p_mock, MockSegmentationProvider)
    assert p_mock.provider_name == "mock"

    p_fallback = get_segmentation_provider("unknown_provider")
    assert isinstance(p_fallback, OpenCVSubjectGuidedSegmentationProvider)


def test_mask_refinement_and_metrics():
    """Validates mask refinement morphology, hole filling, feathering, and quality metrics."""
    # Create a test mask with a hole and salt noise
    raw_mask = np.zeros((100, 100), dtype=np.uint8)
    raw_mask[20:80, 20:80] = 255  # Main box
    raw_mask[45:55, 45:55] = 0    # Internal hole
    raw_mask[5:10, 5:10] = 255    # Tiny noise artifact

    refined, metrics = refine_mask(raw_mask, {
        "morph_kernel_size": 3,
        "hole_fill": True,
        "blur_radius": 3,
        "min_component_ratio": 0.05,
    })

    assert refined.shape == (100, 100)
    assert refined.dtype == np.uint8
    # The internal hole should be filled
    assert refined[50, 50] > 200
    # The tiny noise artifact should be removed
    assert refined[7, 7] == 0
    # Metrics must contain genuine calculated scores
    assert "quality_score" in metrics
    assert "coverage_ratio" in metrics
    assert 0.0 <= metrics["quality_score"] <= 1.0
    assert 0.0 <= metrics["coverage_ratio"] <= 1.0


def test_background_reconstruction_and_inpainting():
    """Validates that character area in background is cleanly inpainted."""
    source_bg = np.full((100, 100, 3), 150, dtype=np.uint8)
    # Add high contrast character patch
    source_bg[30:70, 30:70] = [255, 0, 0]

    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    clean_bg = reconstruct_clean_background(source_bg, mask, dilate_radius=5)
    assert clean_bg.shape == (100, 100, 3)
    # The red patch should be inpainted to blend with surrounding gray
    assert not np.array_equal(clean_bg[50, 50], [255, 0, 0])


def test_background_adaptation_modes():
    """Validates all 4 background treatment modes (ORIGINAL, SOFT_BLUR, DEPTH_STYLE, COMIC_STYLE)."""
    bg = np.full((120, 80, 3), 128, dtype=np.uint8)
    # Add patterns
    bg[20:40, :] = 200

    # 1. ORIGINAL
    bg_orig = apply_background_mode(bg, "ORIGINAL")
    assert np.array_equal(bg, bg_orig)

    # 2. SOFT_BLUR
    bg_blur = apply_background_mode(bg, "SOFT_BLUR")
    assert bg_blur.shape == bg.shape
    assert not np.array_equal(bg, bg_blur)

    # 3. DEPTH_STYLE
    bg_depth = apply_background_mode(bg, "DEPTH_STYLE")
    assert bg_depth.shape == bg.shape
    # Vignette makes corner darker than center
    assert bg_depth[0, 0, 0] < bg_depth[60, 40, 0]

    # 4. COMIC_STYLE
    bg_comic = apply_background_mode(bg, "COMIC_STYLE")
    assert bg_comic.shape == bg.shape
    assert not np.array_equal(bg, bg_comic)


def test_composite_generation():
    """Validates alpha blending of RGBA foreground over RGB background."""
    h, w = 100, 100
    fg_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    # Solid red foreground circle in center with 100% alpha
    fg_rgba[30:70, 30:70] = [255, 0, 0, 255]

    bg_rgb = np.zeros((h, w, 3), dtype=np.uint8)
    bg_rgb[:, :] = [0, 0, 255]  # Solid blue background

    composite = generate_composite_image(fg_rgba, bg_rgb)
    assert composite.shape == (h, w, 3)
    # Center should be foreground red
    assert np.array_equal(composite[50, 50], [255, 0, 0])
    # Corner should be background blue
    assert np.array_equal(composite[10, 10], [0, 0, 255])


def test_run_segmentation_pipeline_e2e(test_project_with_consistent_frame, db_session):
    """Validates end-to-end segmentation pipeline execution and DB persistence."""
    data = test_project_with_consistent_frame
    project_id = data["project_id"]
    frame_id = data["consistent_frame_id"]

    results = run_segmentation_pipeline(
        db=db_session,
        project_id=project_id,
        consistent_frame_id=frame_id,
        background_mode="SOFT_BLUR",
        provider_name="opencv_guided",
    )

    assert len(results) == 1
    res = results[0]
    assert res.project_id == project_id
    assert res.consistent_frame_id == frame_id
    assert res.status == "completed"
    assert res.background_mode == "SOFT_BLUR"
    assert res.mask_media_file_id is not None
    assert res.foreground_media_file_id is not None
    assert res.background_media_file_id is not None
    assert res.composite_media_file_id is not None
    assert res.bbox_width is not None and res.bbox_width > 0
    assert res.quality_metrics is not None
    assert "quality_score" in res.quality_metrics

    # Check physical media files exist on disk
    base_storage = get_base_storage_dir()
    mask_media = db_session.query(MediaFile).filter(MediaFile.id == res.mask_media_file_id).first()
    fg_media = db_session.query(MediaFile).filter(MediaFile.id == res.foreground_media_file_id).first()
    bg_media = db_session.query(MediaFile).filter(MediaFile.id == res.background_media_file_id).first()
    comp_media = db_session.query(MediaFile).filter(MediaFile.id == res.composite_media_file_id).first()

    assert (base_storage / mask_media.file_path).exists()
    assert (base_storage / fg_media.file_path).exists()
    assert (base_storage / bg_media.file_path).exists()
    assert (base_storage / comp_media.file_path).exists()


def test_segmentation_api_endpoint(test_project_with_consistent_frame):
    """Validates POST /api/v1/projects/{project_id}/segmentation HTTP endpoint."""
    client = TestClient(app, headers=get_test_auth_headers())
    data = test_project_with_consistent_frame
    project_id = data["project_id"]
    frame_id = data["consistent_frame_id"]

    # 1. Single frame segmentation
    payload = {
        "consistent_frame_id": frame_id,
        "background_mode": "COMIC_STYLE",
    }
    response = client.post(f"/api/v1/projects/{project_id}/segmentation", json=payload)
    assert response.status_code == 200
    res_json = response.json()
    assert res_json["success"] is True
    assert res_json["count"] == 1
    item = res_json["results"][0]
    assert item["consistent_frame_id"] == frame_id
    assert item["background_mode"] == "COMIC_STYLE"
    assert item["mask_media_file_id"] is not None
    assert item["foreground_media_file_id"] is not None
    assert item["composite_media_file_id"] is not None

    # 2. Get Project detail contains segmentation_results
    get_res = client.get(f"/api/v1/projects/{project_id}")
    assert get_res.status_code == 200
    proj_json = get_res.json()["project"]
    assert "segmentation_results" in proj_json
    assert len(proj_json["segmentation_results"]) == 1
    assert proj_json["segmentation_results"][0]["id"] == item["id"]


def test_segmentation_reprocessing_with_new_mode(test_project_with_consistent_frame, db_session):
    """Validates re-segmenting/reprocessing frame with updated background mode."""
    client = TestClient(app, headers=get_test_auth_headers())
    data = test_project_with_consistent_frame
    project_id = data["project_id"]
    frame_id = data["consistent_frame_id"]

    # First run: ORIGINAL mode
    res1 = client.post(
        f"/api/v1/projects/{project_id}/segmentation",
        json={"consistent_frame_id": frame_id, "background_mode": "ORIGINAL"},
    )
    assert res1.status_code == 200
    res1_id = res1.json()["results"][0]["id"]
    assert res1.json()["results"][0]["background_mode"] == "ORIGINAL"

    # Second run: DEPTH_STYLE mode with force_regenerate=True
    res2 = client.post(
        f"/api/v1/projects/{project_id}/segmentation",
        json={
            "consistent_frame_id": frame_id,
            "background_mode": "DEPTH_STYLE",
            "force_regenerate": True,
        },
    )
    assert res2.status_code == 200
    res2_item = res2.json()["results"][0]
    assert res2_item["id"] == res1_id  # Reused same result record cleanly
    assert res2_item["background_mode"] == "DEPTH_STYLE"


def test_segmentation_invalid_inputs(test_project_with_consistent_frame):
    """Validates proper error handling for invalid project, invalid mode, and missing frame."""
    client = TestClient(app, headers=get_test_auth_headers())
    data = test_project_with_consistent_frame
    project_id = data["project_id"]

    # 1. Invalid Project ID (404)
    res_404 = client.post("/api/v1/projects/PROJ-NONEXISTENT/segmentation", json={})
    assert res_404.status_code == 404

    # 2. Path Traversal Project ID (400)
    res_sec = client.post("/api/v1/projects/PROJ..TRAVERSAL/segmentation", json={})
    assert res_sec.status_code == 400

    # 3. Invalid Background Mode (422 validation error)
    res_mode = client.post(
        f"/api/v1/projects/{project_id}/segmentation",
        json={"background_mode": "INVALID_NEON_MODE"},
    )
    assert res_mode.status_code == 422

    # 4. Nonexistent Frame ID (404)
    res_frame = client.post(
        f"/api/v1/projects/{project_id}/segmentation",
        json={"consistent_frame_id": "nonexistent-frame-id-123"},
    )
    assert res_frame.status_code == 404
