"""
3D Reel Studio — Project & Session Schemas
Phase 3: Project Session Persistence
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ProjectCreate(BaseModel):
    """
    Payload for creating a new project.
    """
    name: str = Field(..., min_length=1, max_length=100, description="Name of the 3D Reel project")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Project name cannot be empty or whitespace only.")
        if len(trimmed) > 100:
            raise ValueError("Project name must not exceed 100 characters.")
        return trimmed


class ProjectUpdate(BaseModel):
    """
    Payload for updating an existing project.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Updated project name")
    status: Optional[str] = Field(None, description="Updated project status")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Project name cannot be empty.")
        if len(trimmed) > 100:
            raise ValueError("Project name must not exceed 100 characters.")
        return trimmed

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        allowed = {"draft", "uploaded", "processing", "completed", "failed"}
        val_lower = value.strip().lower()
        if val_lower not in allowed:
            raise ValueError(f"Invalid status '{value}'. Allowed: {', '.join(sorted(allowed))}")
        return val_lower


class MediaFileSummary(BaseModel):
    """
    Summary view of a media file (without internal storage path).
    """
    id: str
    project_id: str
    file_type: str
    original_filename: str
    stored_filename: str
    mime_type: str
    file_size: int
    sha256_hash: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaUploadResponse(BaseModel):
    """
    Response schema for media file upload.
    """
    success: bool = True
    media: MediaFileSummary


class TransformationJobSummary(BaseModel):
    """
    Summary view of a transformation job.
    """
    id: str
    project_id: str
    job_type: str
    status: str
    progress: float
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummary(BaseModel):
    """
    Summary view of a project.
    """
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WordTimestamp(BaseModel):
    """
    Word-level timestamp synchronization point.
    """
    word: str
    start_time: float
    end_time: float


class TranscriptSegmentSummary(BaseModel):
    """
    Segment timestamp breakdown for synchronization.
    """
    id: Optional[str] = None
    sequence: int
    start_time: float
    end_time: float
    text: str
    words: Optional[List[WordTimestamp]] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_words_data(cls, data: Any) -> Any:
        if hasattr(data, "words_data") and getattr(data, "words_data", None):
            raw_words = getattr(data, "words_data")
            if isinstance(raw_words, str):
                try:
                    words_list = json.loads(raw_words)
                    return {
                        "id": getattr(data, "id", None),
                        "sequence": getattr(data, "sequence", 0),
                        "start_time": getattr(data, "start_time", 0.0),
                        "end_time": getattr(data, "end_time", 0.0),
                        "text": getattr(data, "text", ""),
                        "words": words_list,
                    }
                except Exception:
                    pass
        return data


class TranscriptDetail(BaseModel):
    """
    Full transcript object with segmented timestamps.
    """
    id: str
    project_id: str
    audio_media_id: str
    language: Optional[str] = None
    full_text: str
    created_at: Optional[datetime] = None
    segments: List[TranscriptSegmentSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    """
    Response schema for audio transcription.
    """
    success: bool = True
    transcript: TranscriptDetail


class KeyframeSummary(BaseModel):
    """
    Summary of a representative keyframe extracted from a scene.
    """
    id: Optional[str] = None
    timestamp: float
    media_file_id: str
    width: Optional[int] = None
    height: Optional[int] = None

    model_config = {"from_attributes": True}


class VideoSceneSummary(BaseModel):
    """
    Summary of an individual video scene with its keyframe reference.
    """
    id: Optional[str] = None
    sequence: int
    start_time: float
    end_time: float
    duration: float
    keyframe: Optional[KeyframeSummary] = None
    keyframes: List[KeyframeSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def populate_keyframe(cls, data: Any) -> Any:
        if hasattr(data, "keyframes"):
            kfs = getattr(data, "keyframes", []) or []
            first_kf = kfs[0] if kfs else None
            first_kf_dict = None
            if first_kf:
                first_kf_dict = {
                    "id": getattr(first_kf, "id", None),
                    "timestamp": getattr(first_kf, "timestamp", 0.0),
                    "media_file_id": getattr(first_kf, "media_file_id", ""),
                    "width": getattr(first_kf, "width", None),
                    "height": getattr(first_kf, "height", None),
                }
            return {
                "id": getattr(data, "id", None),
                "sequence": getattr(data, "sequence", 0),
                "start_time": getattr(data, "start_time", 0.0),
                "end_time": getattr(data, "end_time", 0.0),
                "duration": getattr(data, "duration", 0.0),
                "keyframe": first_kf_dict,
                "keyframes": [
                    {
                        "id": getattr(k, "id", None),
                        "timestamp": getattr(k, "timestamp", 0.0),
                        "media_file_id": getattr(k, "media_file_id", ""),
                        "width": getattr(k, "width", None),
                        "height": getattr(k, "height", None),
                    }
                    for k in kfs
                ],
            }
        return data


class VideoAnalysisDetail(BaseModel):
    """
    Full structured video metadata and scene breakdown.
    """
    id: str
    project_id: str
    source_media_id: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: Optional[str] = None
    pixel_format: Optional[str] = None
    aspect_ratio: str
    created_at: Optional[datetime] = None
    scenes: List[VideoSceneSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class VideoAnalysisResponse(BaseModel):
    """
    Response envelope for video analysis.
    """
    success: bool = True
    analysis: VideoAnalysisDetail


class FacialLandmarkPoint(BaseModel):
    """
    2D coordinate of a facial landmark.
    """
    name: str
    x: float
    y: float


class FaceDetectionSummary(BaseModel):
    """
    Face bounding box and landmarks at a video timestamp.
    """
    id: Optional[str] = None
    timestamp: float
    frame_reference: Optional[str] = None
    x: float
    y: float
    width: float
    height: float
    confidence: float
    landmarks: List[FacialLandmarkPoint] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_landmarks(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        if hasattr(data, "landmarks_data"):
            lm_json = getattr(data, "landmarks_data", None)
            landmarks_list = []
            if lm_json:
                try:
                    parsed = json.loads(lm_json)
                    if isinstance(parsed, list):
                        landmarks_list = parsed
                except Exception:
                    pass
            return {
                "id": getattr(data, "id", None),
                "timestamp": getattr(data, "timestamp", 0.0),
                "frame_reference": getattr(data, "frame_reference", None),
                "x": getattr(data, "x", 0.0),
                "y": getattr(data, "y", 0.0),
                "width": getattr(data, "width", 0.0),
                "height": getattr(data, "height", 0.0),
                "confidence": getattr(data, "confidence", 1.0),
                "landmarks": landmarks_list,
            }
        return data


class FaceReferenceSummary(BaseModel):
    """
    High quality selected face reference.
    """
    id: Optional[str] = None
    media_file_id: str
    timestamp: float
    quality_score: float

    model_config = {"from_attributes": True}


class PoseLandmarkSummary(BaseModel):
    """
    Individual keypoint/landmark for body pose.
    """
    landmark_index: int
    landmark_name: str
    x: float
    y: float
    z: Optional[float] = 0.0
    visibility: float = 1.0

    model_config = {"from_attributes": True}


class PoseDetectionSummary(BaseModel):
    """
    Pose detection instance for a subject at a timestamp.
    """
    id: Optional[str] = None
    timestamp: float
    frame_reference: Optional[str] = None
    confidence: float = 1.0
    landmarks: List[PoseLandmarkSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DetectedSubjectSummary(BaseModel):
    """
    Human subject tracked across frames with face & pose detections.
    """
    id: Optional[str] = None
    sequence: int = 0
    is_primary: bool = False
    confidence: float = 1.0
    face_detections: List[FaceDetectionSummary] = Field(default_factory=list)
    pose_detections: List[PoseDetectionSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class VisionAnalysisDetail(BaseModel):
    """
    Structured vision analysis detailing primary subject, detected faces, face references, and poses.
    """
    id: str
    project_id: str
    source_media_id: str
    primary_subject_id: Optional[str] = None
    faces_detected: int = 0
    pose_frames: int = 0
    face_references: List[FaceReferenceSummary] = Field(default_factory=list)
    subjects: List[DetectedSubjectSummary] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def populate_counts(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        faces_count = getattr(data, "faces_detected_count", 0)
        poses_count = getattr(data, "pose_frames_count", 0)
        return {
            "id": getattr(data, "id", None),
            "project_id": getattr(data, "project_id", None),
            "source_media_id": getattr(data, "source_media_id", None),
            "primary_subject_id": getattr(data, "primary_subject_id", None),
            "faces_detected": faces_count,
            "pose_frames": poses_count,
            "face_references": getattr(data, "face_references", []) or [],
            "subjects": getattr(data, "subjects", []) or [],
            "created_at": getattr(data, "created_at", None),
        }


class VisionAnalysisResponse(BaseModel):
    """
    Response schema for vision analysis.
    """
    success: bool = True
    analysis: VisionAnalysisDetail


class ComicGenerationRequest(BaseModel):
    """
    Request payload for triggering 3D comic style generation.
    Supports single scene or controlled batch of scene IDs.
    """
    scene_id: Optional[str] = Field(None, description="Optional single scene ID to generate")
    scene_ids: Optional[List[str]] = Field(None, description="Optional list of scene IDs for batch generation")
    style_preset: Optional[str] = Field("3d-comic", description="Visual style preset (e.g. '3d-comic', 'cyber-hero', 'manga-noir')")
    prompt_override: Optional[str] = Field(None, description="Optional custom prompt directive")


class ComicFrameSummary(BaseModel):
    """
    Summary view of a generated 3D comic frame.
    """
    id: str
    generation_id: str
    scene_id: Optional[str] = None
    source_keyframe_id: Optional[str] = None
    output_media_file_id: Optional[str] = None
    timestamp: float = 0.0
    width: int = 1024
    height: int = 1792
    prompt_version: Optional[str] = None
    status: str = "completed"
    error_code: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ComicGenerationDetail(BaseModel):
    """
    Full detail of a 3D comic style generation run.
    """
    id: str
    project_id: str
    provider: str
    model: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    frames: List[ComicFrameSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ComicGenerationResponse(BaseModel):
    """
    Response envelope for 3D comic generation.
    """
    success: bool = True
    generation: ComicGenerationDetail


class CharacterConsistencyProfileDetail(BaseModel):
    """
    Project-local character consistency profile for the primary subject.
    Phase 10: Identity + Temporal Consistency Engine
    """
    id: str
    project_id: str
    subject_id: Optional[str] = None
    canonical_reference_id: Optional[str] = None
    style_version: str = "v1-3d-comic-lock"
    profile_version: str = "v1.0"
    descriptor_metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ConsistencyProfileResponse(BaseModel):
    """
    Response envelope for character consistency profile.
    """
    success: bool = True
    profile: CharacterConsistencyProfileDetail


class ConsistencyGenerationRequest(BaseModel):
    """
    Request payload for identity + temporal consistency generation.
    Supports single scene or controlled batch of scene IDs.
    """
    scene_id: Optional[str] = Field(None, description="Optional single scene ID to generate consistently")
    scene_ids: Optional[List[str]] = Field(None, description="Optional list of scene IDs for batch consistency generation")
    style_preset: Optional[str] = Field("3d-comic", description="Visual style preset lock (e.g. '3d-comic', 'cyber-hero', 'manga-noir')")
    prompt_override: Optional[str] = Field(None, description="Optional custom prompt directive")
    force_regenerate: Optional[bool] = Field(False, description="Force regeneration of already consistent frames")


class ConsistentComicFrameSummary(BaseModel):
    """
    Summary view of an identity-consistent and temporally coherent 3D comic frame.
    """
    id: str
    consistency_generation_id: str
    scene_id: Optional[str] = None
    source_comic_frame_id: Optional[str] = None
    output_media_file_id: Optional[str] = None
    sequence: int = 0
    previous_frame_id: Optional[str] = None
    timestamp: float = 0.0
    width: int = 1024
    height: int = 1792
    prompt_version: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None
    status: str = "completed"
    error_code: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ConsistencyGenerationDetail(BaseModel):
    """
    Full detail of an identity + temporal consistency generation run.
    """
    id: str
    project_id: str
    profile_id: Optional[str] = None
    provider: str
    model: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    frames: List[ConsistentComicFrameSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ConsistencyGenerationResponse(BaseModel):
    """
    Response envelope for consistency generation.
    """
    success: bool = True
    generation: ConsistencyGenerationDetail


class SegmentationRequest(BaseModel):
    """
    Request payload for foreground segmentation and background adaptation.
    Supports single frame, batch of frames, or scene targets.
    Phase 11: Foreground Segmentation + Dynamic Background
    """
    consistent_frame_id: Optional[str] = Field(None, description="Optional single consistent comic frame ID to segment")
    consistent_frame_ids: Optional[List[str]] = Field(None, description="Optional list of consistent comic frame IDs for batch segmentation")
    scene_id: Optional[str] = Field(None, description="Optional scene ID to segment")
    scene_ids: Optional[List[str]] = Field(None, description="Optional list of scene IDs to segment")
    background_mode: Optional[str] = Field("ORIGINAL", description="Background adaptation mode: ORIGINAL, SOFT_BLUR, DEPTH_STYLE, COMIC_STYLE")
    refinement_params: Optional[Dict[str, Any]] = Field(None, description="Optional mask refinement parameters (e.g. blur_radius, hole_fill)")
    force_regenerate: Optional[bool] = Field(False, description="Force re-segmentation even if results exist")

    @field_validator("background_mode")
    @classmethod
    def validate_background_mode(cls, value: Optional[str]) -> str:
        if not value:
            return "ORIGINAL"
        allowed = {"ORIGINAL", "SOFT_BLUR", "DEPTH_STYLE", "COMIC_STYLE"}
        val_upper = value.strip().upper()
        if val_upper not in allowed:
            raise ValueError(f"Invalid background_mode '{value}'. Allowed modes: {', '.join(sorted(allowed))}")
        return val_upper


class SegmentationResultDetail(BaseModel):
    """
    Detailed summary of a foreground segmentation and dynamic background layered scene.
    Phase 11: Foreground Segmentation + Dynamic Background
    """
    id: str
    project_id: str
    consistent_frame_id: Optional[str] = None
    source_comic_frame_id: Optional[str] = None
    source_scene_id: Optional[str] = None
    source_keyframe_id: Optional[str] = None
    provider: str = "opencv_guided"
    model: str = "grabcut_pose_prior"
    status: str = "completed"
    background_mode: str = "ORIGINAL"
    mask_media_file_id: Optional[str] = None
    foreground_media_file_id: Optional[str] = None
    background_media_file_id: Optional[str] = None
    composite_media_file_id: Optional[str] = None
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
    quality_metrics: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SegmentationResponse(BaseModel):
    """
    Response envelope for foreground segmentation operations.
    """
    success: bool = True
    results: List[SegmentationResultDetail] = Field(default_factory=list)
    count: int = 0


class LyricStyleSummary(BaseModel):
    """
    Visual styling configuration for kinetic lyric rendering.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    id: str
    project_id: str
    name: str
    font_family: str = "Outfit"
    font_size: int = 64
    font_weight: str = "bold"
    fill_color: str = "#FFFFFF"
    outline_color: Optional[str] = "#000000"
    outline_width: int = 4
    shadow_color: Optional[str] = "rgba(0,0,0,0.8)"
    shadow_offset_x: int = 4
    shadow_offset_y: int = 4
    shadow_blur: int = 8
    letter_spacing: int = 2
    line_spacing: float = 1.15
    text_transform: str = "uppercase"
    alignment: str = "center"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LyricAnimationSummary(BaseModel):
    """
    Animation preset defining motion curves and timing for lyrics.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    id: str
    project_id: str
    name: str
    animation_type: str = "POP"
    duration: float = 0.35
    easing: str = "ease_out_back"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LyricSegmentSummary(BaseModel):
    """
    Displayable lyric and kinetic text segment.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    id: str
    project_id: str
    transcript_segment_id: Optional[str] = None
    style_id: Optional[str] = None
    animation_id: Optional[str] = None
    sequence: int = 0
    start_time: float
    end_time: float
    text: str
    position_x: float = 0.5
    position_y: float = 0.75
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    z_layer: int = 1
    enabled: bool = True
    words: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def parse_words(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        if hasattr(data, "words_data") and getattr(data, "words_data", None):
            raw = getattr(data, "words_data")
            if isinstance(raw, str):
                try:
                    words = json.loads(raw)
                    return {
                        "id": data.id,
                        "project_id": data.project_id,
                        "transcript_segment_id": data.transcript_segment_id,
                        "style_id": data.style_id,
                        "animation_id": data.animation_id,
                        "sequence": data.sequence,
                        "start_time": data.start_time,
                        "end_time": data.end_time,
                        "text": data.text,
                        "position_x": data.position_x,
                        "position_y": data.position_y,
                        "scale": data.scale,
                        "rotation": data.rotation,
                        "opacity": data.opacity,
                        "z_layer": data.z_layer,
                        "enabled": data.enabled,
                        "words": words,
                        "created_at": getattr(data, "created_at", None),
                        "updated_at": getattr(data, "updated_at", None),
                    }
                except Exception:
                    pass
        return data


class LyricSegmentUpdate(BaseModel):
    """
    Update payload for a specific lyric segment.
    """
    text: Optional[str] = None
    style_id: Optional[str] = None
    animation_id: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    scale: Optional[float] = None
    rotation: Optional[float] = None
    opacity: Optional[float] = None
    z_layer: Optional[int] = None
    enabled: Optional[bool] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class LyricSyncRequest(BaseModel):
    """
    Payload for syncing transcript segments into lyric segments.
    """
    force_recreate: Optional[bool] = Field(False, description="Recreate all segments from transcript")
    default_style_name: Optional[str] = Field(None, description="Default style to apply")
    default_animation_name: Optional[str] = Field(None, description="Default animation to apply")


class LyricSyncResponse(BaseModel):
    """
    Response envelope for lyric synchronization.
    """
    success: bool = True
    segments: List[LyricSegmentSummary] = Field(default_factory=list)
    styles: List[LyricStyleSummary] = Field(default_factory=list)
    animations: List[LyricAnimationSummary] = Field(default_factory=list)
    count: int = 0


class LyricPreviewRequest(BaseModel):
    """
    Request payload for rendering a text-behind-character preview frame.
    """
    scene_id: Optional[str] = Field(None, description="Optional scene ID to preview")
    segmentation_id: Optional[str] = Field(None, description="Optional segmentation result ID")
    lyric_segment_id: Optional[str] = Field(None, description="Optional lyric segment ID")
    timestamp: Optional[float] = Field(None, description="Optional timestamp for preview")
    text_override: Optional[str] = Field(None, description="Optional live text override")
    position_x: Optional[float] = Field(None, description="Optional normalized X override (0.0 - 1.0)")
    position_y: Optional[float] = Field(None, description="Optional normalized Y override (0.0 - 1.0)")
    scale: Optional[float] = Field(None, description="Optional scale override")
    opacity: Optional[float] = Field(None, description="Optional opacity override")
    style_id: Optional[str] = Field(None, description="Optional style ID override")
    animation_id: Optional[str] = Field(None, description="Optional animation ID override")


class LyricPreviewDetail(BaseModel):
    """
    Detail of a rendered text-behind-character preview frame.
    """
    id: str
    project_id: str
    lyric_segment_id: Optional[str] = None
    scene_id: Optional[str] = None
    segmentation_id: Optional[str] = None
    timestamp: float
    output_media_file_id: str
    compositing_metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class LyricPreviewResponse(BaseModel):
    """
    Response envelope for lyric preview generation.
    """
    success: bool = True
    preview: LyricPreviewDetail


class LyricListResponse(BaseModel):
    """
    Response envelope for listing all lyric configurations.
    """
    success: bool = True
    segments: List[LyricSegmentSummary] = Field(default_factory=list)
    styles: List[LyricStyleSummary] = Field(default_factory=list)
    animations: List[LyricAnimationSummary] = Field(default_factory=list)
    previews: List[LyricPreviewDetail] = Field(default_factory=list)


class RenderJobRequest(BaseModel):
    """
    Request configuration for rendering final 9:16 vertical Reel.
    Phase 13: Final Video Compositing + 9:16 Reel Rendering
    """
    output_width: int = Field(1080, ge=360, le=3840, description="Output video width in pixels")
    output_height: int = Field(1920, ge=640, le=3840, description="Output video height in pixels")
    fps: float = Field(30.0, ge=10.0, le=120.0, description="Output video frames per second")
    video_codec: str = Field("libx264", description="Video encoder codec (e.g. libx264)")
    audio_codec: str = Field("aac", description="Audio encoder codec (e.g. aac)")
    include_audio: bool = Field(True, description="Whether to multiplex original audio track")
    include_lyrics: bool = Field(True, description="Whether to composite kinetic lyrics")
    force_rerender: bool = Field(False, description="Whether to re-render even if a completed job exists")


class RenderJobSummary(BaseModel):
    """
    Summary of a final video render job.
    """
    id: str
    project_id: str
    source_media_id: Optional[str] = None
    status: str
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    duration: Optional[float] = None
    output_media_file_id: Optional[str] = None
    progress: float = 0.0
    stage_message: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    render_config: Optional[Dict[str, Any]] = None
    render_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RenderJobResponse(BaseModel):
    """
    Response envelope for a single render job.
    """
    success: bool = True
    job: RenderJobSummary


class RenderJobListResponse(BaseModel):
    """
    Response envelope for listing project render jobs.
    """
    success: bool = True
    jobs: List[RenderJobSummary] = Field(default_factory=list)
    count: int = 0
    latest_render: Optional[RenderJobSummary] = None


class ProjectDetail(BaseModel):
    """
    Complete view of a project including attached media, jobs, transcripts, video analyses, vision analyses, comic generations, consistency generations, segmentation results, lyric configurations, and render jobs.
    """
    id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    media_files: List[MediaFileSummary] = Field(default_factory=list)
    transformation_jobs: List[TransformationJobSummary] = Field(default_factory=list)
    transcripts: List[TranscriptDetail] = Field(default_factory=list)
    video_analyses: List[VideoAnalysisDetail] = Field(default_factory=list)
    vision_analyses: List[VisionAnalysisDetail] = Field(default_factory=list)
    comic_generations: List[ComicGenerationDetail] = Field(default_factory=list)
    consistency_profiles: List[CharacterConsistencyProfileDetail] = Field(default_factory=list)
    consistency_generations: List[ConsistencyGenerationDetail] = Field(default_factory=list)
    segmentation_results: List[SegmentationResultDetail] = Field(default_factory=list)
    lyric_styles: List[LyricStyleSummary] = Field(default_factory=list)
    lyric_animations: List[LyricAnimationSummary] = Field(default_factory=list)
    lyric_segments: List[LyricSegmentSummary] = Field(default_factory=list)
    lyric_previews: List[LyricPreviewDetail] = Field(default_factory=list)
    render_jobs: List[RenderJobSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}



class ProjectResponse(BaseModel):
    """
    Single project response envelope.
    """
    success: bool = True
    project: ProjectSummary


class ProjectDetailResponse(BaseModel):
    """
    Detailed project response envelope.
    """
    success: bool = True
    project: ProjectDetail


class ProjectListResponse(BaseModel):
    """
    Multiple projects list response envelope.
    """
    success: bool = True
    projects: List[ProjectSummary]
    count: int


class StorageAuditSummary(BaseModel):
    total_media_records: int
    healthy_count: int
    missing_count: int
    zero_byte_count: int
    checksum_mismatch_count: int
    unreferenced_disk_files_count: int
    stale_temp_dirs_count: int


class StorageAuditResponse(BaseModel):
    """
    Diagnostic storage audit response for a project.
    """
    success: bool = True
    project_id: str
    is_healthy: bool
    summary: StorageAuditSummary
    missing_files: List[Dict[str, Any]] = Field(default_factory=list)
    zero_byte_files: List[Dict[str, Any]] = Field(default_factory=list)
    checksum_mismatches: List[Dict[str, Any]] = Field(default_factory=list)
    unreferenced_files: List[Dict[str, Any]] = Field(default_factory=list)
    stale_temp_dirs: List[str] = Field(default_factory=list)


class StorageCleanupRequest(BaseModel):
    """
    Parameters for storage cleanup maintenance.
    """
    dry_run: bool = Field(True, description="When true, reports actions without modifying or deleting files.")
    clean_stale_temp: bool = Field(True, description="Cleans abandoned tmp_job_* folders.")
    clean_unreferenced: bool = Field(False, description="Cleans unreferenced orphaned files on disk.")


class StorageCleanupResponse(BaseModel):
    """
    Response envelope for storage cleanup maintenance.
    """
    success: bool = True
    project_id: str
    dry_run: bool
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list)
    audit_after: Dict[str, Any] = Field(default_factory=dict)



