"""
3D Reel Studio — Kinetic Lyrics & Text-Behind-Character Engine Tests
Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
"""

import json
import os
import io
import pytest
from pathlib import Path
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import SessionLocal, init_db, get_db
from app.models.project import (
    Project,
    MediaFile,
    Transcript,
    TranscriptSegment,
    VideoAnalysis,
    VideoScene,
    SceneKeyframe,
    ComicGeneration,
    ComicFrame,
    ConsistencyGeneration,
    ConsistentComicFrame,
    SegmentationResult,
    LyricStyle,
    LyricAnimation,
    LyricSegment,
    LyricPreview,
    generate_uuid,
)
from app.services.storage import get_project_storage_dir
from app.services.lyrics import (
    DEFAULT_LYRIC_STYLES,
    DEFAULT_LYRIC_ANIMATIONS,
    KineticTextEngine,
    compute_animation_state,
    ease_out_back,
    ease_out_cubic,
    ease_out_bounce,
    wrap_text_lines,
    get_pil_font,
    composite_text_behind_character,
    get_or_create_default_styles,
    get_or_create_default_animations,
    sync_transcript_to_lyrics,
    generate_lyric_preview,
)

from tests.conftest import get_test_auth_headers

client = TestClient(app, headers=get_test_auth_headers())


@pytest.fixture(scope="module", autouse=True)
def ensure_db_schema():
    """Initializes the database schema including the new lyric tables."""
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
def sample_project_with_layers(db_session: Session):
    """Creates a complete project with transcript and Phase 11 segmentation layers for testing."""
    proj = Project(name="Lyrics Test Project", status="draft")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    # 1. Add MediaFile & Transcript with segments and word timestamps
    audio_media = MediaFile(
        project_id=proj.id,
        file_type="extracted_audio",
        original_filename="test.mp3",
        stored_filename="test.mp3",
        file_path="storage/test.mp3",
        mime_type="audio/mpeg",
    )
    db_session.add(audio_media)
    db_session.commit()

    words_seg1 = [
        {"word": "3D", "start": 0.0, "end": 0.8},
        {"word": "REEL", "start": 0.8, "end": 1.5},
        {"word": "STUDIO", "start": 1.5, "end": 2.5},
    ]

    transcript = Transcript(
        project_id=proj.id,
        audio_media_id=audio_media.id,
        language="en",
        full_text="3D REEL STUDIO HEROIC TRANSFORMATION",
    )
    db_session.add(transcript)
    db_session.commit()

    seg1 = TranscriptSegment(
        transcript_id=transcript.id,
        sequence=0,
        start_time=0.0,
        end_time=2.5,
        text="3D REEL STUDIO",
        words_data=json.dumps(words_seg1),
    )
    seg2 = TranscriptSegment(
        transcript_id=transcript.id,
        sequence=1,
        start_time=2.5,
        end_time=5.0,
        text="HEROIC TRANSFORMATION",
    )
    db_session.add_all([seg1, seg2])
    db_session.commit()

    # 2. Add Video Scene & Keyframe
    analysis = VideoAnalysis(
        project_id=proj.id,
        source_media_id=audio_media.id,
        width=1024,
        height=1792,
        fps=30.0,
        frame_count=150,
        duration=5.0,
        aspect_ratio="9:16",
    )
    db_session.add(analysis)
    db_session.commit()

    scene = VideoScene(
        analysis_id=analysis.id,
        sequence=0,
        start_time=0.0,
        end_time=5.0,
        duration=5.0,
    )
    db_session.add(scene)
    db_session.commit()

    # 3. Create Physical Test Images for Background, Foreground, and Mask
    storage_bg = get_project_storage_dir(proj.id, "segmentation_background")
    storage_fg = get_project_storage_dir(proj.id, "segmentation_foreground")
    storage_mask = get_project_storage_dir(proj.id, "segmentation_mask")

    # Layer 0: Background image (Dark Navy Blue)
    bg_img = Image.new("RGB", (512, 896), (15, 25, 45))
    bg_path = storage_bg / f"bg_{generate_uuid()}.png"
    bg_img.save(bg_path, format="PNG")

    # Layer 2: Foreground character (Bright Red square in center with alpha 255)
    fg_img = Image.new("RGBA", (512, 896), (0, 0, 0, 0))
    fg_draw = ImageDraw.Draw(fg_img)
    # Character occupies center (150, 200) to (362, 700)
    fg_draw.rectangle([150, 200, 362, 700], fill=(255, 46, 99, 255))
    fg_path = storage_fg / f"fg_{generate_uuid()}.png"
    fg_img.save(fg_path, format="PNG")

    # Mask: Grayscale 255 in center, 0 outside
    mask_img = Image.new("L", (512, 896), 0)
    mask_draw = ImageDraw.Draw(mask_img)
    mask_draw.rectangle([150, 200, 362, 700], fill=255)
    mask_path = storage_mask / f"mask_{generate_uuid()}.png"
    mask_img.save(mask_path, format="PNG")

    bg_media = MediaFile(
        project_id=proj.id,
        file_type="segmentation_background",
        original_filename="bg.png",
        stored_filename=bg_path.name,
        file_path=str(bg_path),
        mime_type="image/png",
    )
    fg_media = MediaFile(
        project_id=proj.id,
        file_type="segmentation_foreground",
        original_filename="fg.png",
        stored_filename=fg_path.name,
        file_path=str(fg_path),
        mime_type="image/png",
    )
    mask_media = MediaFile(
        project_id=proj.id,
        file_type="segmentation_mask",
        original_filename="mask.png",
        stored_filename=mask_path.name,
        file_path=str(mask_path),
        mime_type="image/png",
    )
    db_session.add_all([bg_media, fg_media, mask_media])
    db_session.commit()

    seg_res = SegmentationResult(
        project_id=proj.id,
        source_scene_id=scene.id,
        status="completed",
        background_mode="ORIGINAL",
        background_media_file_id=bg_media.id,
        foreground_media_file_id=fg_media.id,
        mask_media_file_id=mask_media.id,
    )
    db_session.add(seg_res)
    db_session.commit()

    return {
        "project": proj,
        "transcript": transcript,
        "scene": scene,
        "segmentation": seg_res,
        "bg_path": bg_path,
        "fg_path": fg_path,
        "mask_path": mask_path,
    }


def test_lyric_default_styles_and_animations(db_session: Session):
    """Verifies default styles and animations initialization."""
    proj = Project(name="Style Test Proj")
    db_session.add(proj)
    db_session.commit()

    styles = get_or_create_default_styles(db_session, proj.id)
    assert len(styles) == len(DEFAULT_LYRIC_STYLES)
    style_names = {s.name for s in styles}
    assert "STYLE_01_BOLD_CINEMATIC" in style_names
    assert "STYLE_03_COMIC_IMPACT" in style_names
    assert "STYLE_04_NEON_CYBER" in style_names

    anims = get_or_create_default_animations(db_session, proj.id)
    assert len(anims) == len(DEFAULT_LYRIC_ANIMATIONS)
    anim_types = {a.animation_type for a in anims}
    assert "POP" in anim_types
    assert "SCALE_IN" in anim_types
    assert "SLIDE_UP" in anim_types


def test_transcript_to_lyric_sync_and_timing(db_session: Session, sample_project_with_layers):
    """Verifies that transcript segments convert faithfully to LyricSegments with exact timestamps."""
    proj = sample_project_with_layers["project"]

    segments, styles, animations = sync_transcript_to_lyrics(db_session, proj.id)
    assert len(segments) == 2
    assert segments[0].sequence == 0
    assert segments[0].start_time == 0.0
    assert segments[0].end_time == 2.5
    assert segments[0].text == "3D REEL STUDIO"
    assert segments[0].z_layer == 1  # Behind character

    # Verify word timestamps preserved
    assert segments[0].words_data is not None
    words = json.loads(segments[0].words_data)
    assert len(words) == 3
    assert words[0]["word"] == "3D"

    assert segments[1].sequence == 1
    assert segments[1].start_time == 2.5
    assert segments[1].end_time == 5.0
    assert segments[1].text == "HEROIC TRANSFORMATION"


def test_easing_and_animation_state_computation():
    """Verifies deterministic easing and motion computation across all animation types."""
    # 1. Easing functions
    assert ease_out_cubic(0.0) == 0.0
    assert ease_out_cubic(1.0) == 1.0
    assert ease_out_back(0.0) < 0.1
    assert ease_out_bounce(1.0) == 1.0

    # 2. Animation state for POP
    pop_start = compute_animation_state("POP", progress=0.1, anim_duration=0.35, segment_duration=2.0)
    assert pop_start.opacity > 0.0
    pop_end = compute_animation_state("POP", progress=1.0, anim_duration=0.35, segment_duration=2.0)
    assert pop_end.opacity == 1.0
    assert pop_end.scale == 1.0

    # 3. Animation state for SLIDE_UP
    slide_start = compute_animation_state("SLIDE_UP", progress=0.0, anim_duration=0.35, segment_duration=2.0)
    assert slide_start.offset_y > 0.0
    slide_end = compute_animation_state("SLIDE_UP", progress=1.0, anim_duration=0.35, segment_duration=2.0)
    assert abs(slide_end.offset_y) < 1.0

    # 4. Word by word
    words = [{"word": "A", "start": 0.0}, {"word": "B", "start": 1.0}, {"word": "C", "start": 2.0}]
    wbw_state = compute_animation_state("WORD_BY_WORD", progress=0.5, words_data=words, current_time=1.5, start_time=0.0)
    assert wbw_state.active_word_index == 1


def test_text_wrapping_and_layout():
    """Verifies multiline wrapping and safe bounding box constraints."""
    font = get_pil_font("Outfit", 48, "bold")
    short_text = "SHORT TITLE"
    lines_short = wrap_text_lines(short_text, font, max_width=600, text_transform="uppercase")
    assert len(lines_short) == 1
    assert lines_short[0] == "SHORT TITLE"

    long_text = "THIS IS A VERY LONG LYRIC SEGMENT THAT MUST WRAP ACROSS MULTIPLE LINES ACCORDINGLY"
    lines_long = wrap_text_lines(long_text, font, max_width=300, text_transform="uppercase")
    assert len(lines_long) > 1
    for line in lines_long:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        assert w <= 350 or len(line.split()) == 1


def test_render_kinetic_text_layer_rgba(db_session: Session, sample_project_with_layers):
    """Verifies rendering transparent RGBA kinetic text layer with styling and positioning."""
    proj = sample_project_with_layers["project"]
    styles = get_or_create_default_styles(db_session, proj.id)
    style = styles[0]

    anim_state = compute_animation_state("POP", progress=1.0)
    text_layer = KineticTextEngine.render_text_layer(
        text="CYBER REEL",
        canvas_width=512,
        canvas_height=896,
        style=style,
        anim_state=anim_state,
        pos_x=0.5,
        pos_y=0.5,
    )

    assert text_layer.mode == "RGBA"
    assert text_layer.size == (512, 896)
    # Check that text layer has non-zero alpha pixels where text was drawn
    alpha_chan = text_layer.split()[3]
    alpha_np = list(alpha_chan.getdata())
    assert any(a > 0 for a in alpha_np)
    # And corners should remain completely transparent
    assert text_layer.getpixel((0, 0))[3] == 0


def test_composite_text_behind_character_layering():
    """
    CRITICAL TEST: Verifies that kinetic text appears BEHIND the character:
    - Layer 0: Background (Blue: 0, 0, 255)
    - Layer 1: Kinetic Text (White: 255, 255, 255 spanning entire canvas)
    - Layer 2: Character Foreground (Green: 0, 255, 0 with opaque mask in upper half only)
    
    Expected result:
    - Upper half (where character is opaque): Result pixel is GREEN (Character covers Text).
    - Lower half (where character is transparent): Result pixel is WHITE (Text covers Background).
    """
    W, H = 200, 200

    # Layer 0: Solid Blue Background
    bg_img = Image.new("RGB", (W, H), (0, 0, 255))

    # Layer 1: Solid White Text Layer
    text_img = Image.new("RGBA", (W, H), (255, 255, 255, 255))

    # Layer 2: Solid Green Character Foreground
    fg_img = Image.new("RGBA", (W, H), (0, 255, 0, 255))

    # Mask: Top half (y < 100) = 255 (Character present), Bottom half (y >= 100) = 0 (Transparent)
    mask_img = Image.new("L", (W, H), 0)
    mask_draw = ImageDraw.Draw(mask_img)
    mask_draw.rectangle([0, 0, W, 99], fill=255)

    composite = composite_text_behind_character(
        bg_image=bg_img,
        text_layer=text_img,
        fg_image=fg_img,
        alpha_mask=mask_img,
    )

    assert composite.size == (W, H)
    assert composite.mode == "RGB"

    # In top half (x=100, y=50), Character foreground covers text -> Expected Green (0, 255, 0)
    top_pixel = composite.getpixel((100, 50))
    assert top_pixel == (0, 255, 0), f"Expected character foreground (0, 255, 0), got {top_pixel}"

    # In bottom half (x=100, y=150), Character is transparent -> Expected Text (255, 255, 255)
    bottom_pixel = composite.getpixel((100, 150))
    assert bottom_pixel == (255, 255, 255), f"Expected kinetic text (255, 255, 255), got {bottom_pixel}"


def test_lyric_sync_api_endpoint(sample_project_with_layers):
    """Tests POST /api/v1/projects/{project_id}/lyrics/sync."""
    proj = sample_project_with_layers["project"]
    resp = client.post(f"/api/v1/projects/{proj.id}/lyrics/sync", json={"force_recreate": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 2
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "3D REEL STUDIO"
    assert len(data["styles"]) >= 5
    assert len(data["animations"]) >= 8


def test_get_lyrics_api_endpoint(sample_project_with_layers):
    """Tests GET /api/v1/projects/{project_id}/lyrics."""
    proj = sample_project_with_layers["project"]
    resp = client.get(f"/api/v1/projects/{proj.id}/lyrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["segments"]) == 2
    assert len(data["styles"]) >= 5


def test_update_lyric_segment_api(sample_project_with_layers):
    """Tests PATCH /api/v1/projects/{project_id}/lyrics/segments/{segment_id}."""
    proj = sample_project_with_layers["project"]
    # First sync to ensure segments exist
    sync_resp = client.post(f"/api/v1/projects/{proj.id}/lyrics/sync", json={})
    seg_id = sync_resp.json()["segments"][0]["id"]

    # Update position and custom text
    update_resp = client.patch(
        f"/api/v1/projects/{proj.id}/lyrics/segments/{seg_id}",
        json={
            "text": "UPDATED CUSTOM LYRIC",
            "position_x": 0.5,
            "position_y": 0.8,
            "scale": 1.2,
            "opacity": 0.95,
        },
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["text"] == "UPDATED CUSTOM LYRIC"
    assert updated_data["position_y"] == 0.8
    assert updated_data["scale"] == 1.2
    assert updated_data["opacity"] == 0.95


def test_preview_lyric_composite_api(sample_project_with_layers):
    """Tests POST /api/v1/projects/{project_id}/lyrics/preview with real layers."""
    proj = sample_project_with_layers["project"]
    scene = sample_project_with_layers["scene"]

    resp = client.post(
        f"/api/v1/projects/{proj.id}/lyrics/preview",
        json={
            "scene_id": scene.id,
            "timestamp": 1.0,
            "text_override": "HERO BEHIND TEXT",
            "position_x": 0.5,
            "position_y": 0.5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    preview = data["preview"]
    assert preview["project_id"] == proj.id
    assert preview["output_media_file_id"] is not None
    assert preview["compositing_metadata"]["layer_order"] == ["background", "kinetic_text", "foreground_character"]

    # Verify preview file was physically created
    media_id = preview["output_media_file_id"]
    file_resp = client.get(f"/api/v1/projects/{proj.id}/media/{media_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "image/png"


def test_lyric_error_handling():
    """Tests validation, path traversal, and missing resource error cases."""
    # 1. Invalid Project ID
    resp = client.post("/api/v1/projects/../invalid/lyrics/sync", json={})
    assert resp.status_code in (400, 404)

    # 2. Nonexistent Project ID
    resp = client.post("/api/v1/projects/PROJ-NONEXISTENT/lyrics/sync", json={})
    assert resp.status_code == 404

    # 3. Nonexistent Segment Update
    resp = client.patch("/api/v1/projects/PROJ-NONEXISTENT/lyrics/segments/seg-fake", json={"text": "test"})
    assert resp.status_code == 404

    # 4. Preview with no segmentation
    empty_proj = client.post("/api/v1/projects", json={"name": "Empty Proj"}).json()["project"]
    resp = client.post(f"/api/v1/projects/{empty_proj['id']}/lyrics/preview", json={})
    assert resp.status_code == 400
    assert "LYRIC_PREVIEW_ERROR" in resp.text or "segmentation" in resp.text
