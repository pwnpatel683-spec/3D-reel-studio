"""
3D Reel Studio — Database Models (Project, MediaFile, TransformationJob)
Phase 3: Project Session Persistence
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Boolean,
    JSON,
)
from sqlalchemy.orm import relationship
from app.db.session import Base


def generate_project_id() -> str:
    """Generates a human-friendly unique project ID (e.g. PROJ-A1B2C3D4)."""
    return f"PROJ-{uuid.uuid4().hex[:8].upper()}"


def generate_uuid() -> str:
    """Generates a standard UUID4 string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Returns current UTC timestamp timezone-aware."""
    return datetime.now(timezone.utc)


class Project(Base):
    """
    Project model representing a 3D Reel transformation studio session.
    """
    __tablename__ = "projects"

    id = Column(String(50), primary_key=True, default=generate_project_id, index=True)
    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default="USR-DEFAULT-DEV", index=True)
    name = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="draft", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    # Relationships with cascading delete
    user = relationship("User", back_populates="projects")
    media_files = relationship(
        "MediaFile",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(MediaFile.created_at)",
    )
    transformation_jobs = relationship(
        "TransformationJob",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(TransformationJob.created_at)",
    )
    transcripts = relationship(
        "Transcript",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(Transcript.created_at)",
    )
    video_analyses = relationship(
        "VideoAnalysis",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(VideoAnalysis.created_at)",
    )
    vision_analyses = relationship(
        "VisionAnalysis",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(VisionAnalysis.created_at)",
    )
    comic_generations = relationship(
        "ComicGeneration",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(ComicGeneration.created_at)",
    )
    consistency_profiles = relationship(
        "CharacterConsistencyProfile",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(CharacterConsistencyProfile.created_at)",
    )
    consistency_generations = relationship(
        "ConsistencyGeneration",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(ConsistencyGeneration.created_at)",
    )
    segmentation_results = relationship(
        "SegmentationResult",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(SegmentationResult.created_at)",
    )
    lyric_styles = relationship(
        "LyricStyle",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="LyricStyle.name",
    )
    lyric_animations = relationship(
        "LyricAnimation",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="LyricAnimation.name",
    )
    lyric_segments = relationship(
        "LyricSegment",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="LyricSegment.sequence",
    )
    lyric_previews = relationship(
        "LyricPreview",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(LyricPreview.created_at)",
    )
    render_jobs = relationship(
        "RenderJob",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(RenderJob.created_at)",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name='{self.name}' status='{self.status}'>"


class MediaFile(Base):
    """
    Media file attached to a project (source video, face reference, extracted audio, render, keyframe).
    """
    __tablename__ = "media_files"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    file_type = Column(String(50), nullable=False, index=True)  # e.g., 'source_video', 'face_reference', 'extracted_audio', 'keyframe_image'
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    sha256_hash = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    project = relationship("Project", back_populates="media_files")

    def __repr__(self) -> str:
        return f"<MediaFile id={self.id} project_id={self.project_id} type='{self.file_type}'>"


class TransformationJob(Base):
    """
    Background AI transformation job tracked for a project.
    """
    __tablename__ = "transformation_jobs"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_type = Column(String(50), nullable=False)  # e.g., '3d_comic_generation', 'transcription', 'video_analysis'
    status = Column(String(30), nullable=False, default="pending", index=True)  # pending, processing, completed, failed
    progress = Column(Float, nullable=False, default=0.0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="transformation_jobs")

    def __repr__(self) -> str:
        return f"<TransformationJob id={self.id} project_id={self.project_id} status='{self.status}'>"


class Transcript(Base):
    """
    AI audio transcript generated from extracted audio.
    Phase 6: Audio Transcription & Timestamps
    """
    __tablename__ = "transcripts"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_media_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    language = Column(String(20), nullable=True)
    full_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="transcripts")
    audio_media = relationship("MediaFile")
    segments = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.sequence",
    )

    def __repr__(self) -> str:
        return f"<Transcript id={self.id} project_id={self.project_id} language='{self.language}'>"


class TranscriptSegment(Base):
    """
    Timestamped transcript segment for synchronization with kinetic lyrics.
    Phase 6: Audio Transcription & Timestamps
    """
    __tablename__ = "transcript_segments"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    transcript_id = Column(String(50), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0, index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    words_data = Column(Text, nullable=True)  # JSON-encoded word-level timestamps if available

    transcript = relationship("Transcript", back_populates="segments")

    def __repr__(self) -> str:
        return f"<TranscriptSegment id={self.id} seq={self.sequence} [{self.start_time:.2f}-{self.end_time:.2f}]>"


class VideoAnalysis(Base):
    """
    Structured video metadata and scene analysis.
    Phase 7: Video Scene & Content Analysis
    """
    __tablename__ = "video_analyses"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_media_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    fps = Column(Float, nullable=False)
    frame_count = Column(Integer, nullable=False)
    duration = Column(Float, nullable=False)
    codec = Column(String(50), nullable=True)
    pixel_format = Column(String(50), nullable=True)
    aspect_ratio = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="video_analyses")
    source_media = relationship("MediaFile")
    scenes = relationship(
        "VideoScene",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="VideoScene.sequence",
    )

    def __repr__(self) -> str:
        return f"<VideoAnalysis id={self.id} project_id={self.project_id} {self.width}x{self.height} dur={self.duration:.1f}s>"


class VideoScene(Base):
    """
    Individual video scene / shot segment.
    Phase 7: Video Scene & Content Analysis
    """
    __tablename__ = "video_scenes"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    analysis_id = Column(String(50), ForeignKey("video_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0, index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)

    analysis = relationship("VideoAnalysis", back_populates="scenes")
    keyframes = relationship(
        "SceneKeyframe",
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="SceneKeyframe.timestamp",
    )

    def __repr__(self) -> str:
        return f"<VideoScene id={self.id} seq={self.sequence} [{self.start_time:.2f}-{self.end_time:.2f}] dur={self.duration:.2f}s>"


class SceneKeyframe(Base):
    """
    Visual representative keyframe extracted from a video scene.
    Phase 7: Video Scene & Content Analysis
    """
    __tablename__ = "scene_keyframes"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    scene_id = Column(String(50), ForeignKey("video_scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(Float, nullable=False)
    media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)

    scene = relationship("VideoScene", back_populates="keyframes")
    media_file = relationship("MediaFile")

    def __repr__(self) -> str:
        return f"<SceneKeyframe id={self.id} scene_id={self.scene_id} t={self.timestamp:.2f}s {self.width}x{self.height}>"


class VisionAnalysis(Base):
    """
    Structured human face, primary subject, face references, and body pose analysis.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "vision_analyses"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_media_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    primary_subject_id = Column(String(50), nullable=True)
    faces_detected_count = Column(Integer, nullable=False, default=0)
    pose_frames_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="vision_analyses")
    source_media = relationship("MediaFile")
    subjects = relationship(
        "DetectedSubject",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="DetectedSubject.sequence",
    )
    face_references = relationship(
        "FaceReference",
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="FaceReference.timestamp",
    )

    def __repr__(self) -> str:
        return f"<VisionAnalysis id={self.id} project_id={self.project_id} faces={self.faces_detected_count} poses={self.pose_frames_count}>"


class DetectedSubject(Base):
    """
    Tracked human subject across video frames.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "detected_subjects"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    analysis_id = Column(String(50), ForeignKey("vision_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False, default=0, index=True)
    is_primary = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    analysis = relationship("VisionAnalysis", back_populates="subjects")
    face_detections = relationship(
        "FaceDetection",
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="FaceDetection.timestamp",
    )
    face_references = relationship(
        "FaceReference",
        back_populates="subject",
        cascade="all, delete-orphan",
    )
    pose_detections = relationship(
        "PoseDetection",
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="PoseDetection.timestamp",
    )

    def __repr__(self) -> str:
        return f"<DetectedSubject id={self.id} seq={self.sequence} primary={self.is_primary} conf={self.confidence:.2f}>"


class FaceDetection(Base):
    """
    Individual face localization with normalized bounding box and facial landmarks.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "face_detections"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    subject_id = Column(String(50), ForeignKey("detected_subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(Float, nullable=False, index=True)
    frame_reference = Column(String(100), nullable=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    width = Column(Float, nullable=False)
    height = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    landmarks_data = Column(Text, nullable=True)  # JSON-encoded 5-point landmark list
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    subject = relationship("DetectedSubject", back_populates="face_detections")

    def __repr__(self) -> str:
        return f"<FaceDetection id={self.id} t={self.timestamp:.2f}s bbox=({self.x:.2f},{self.y:.2f},{self.width:.2f},{self.height:.2f}) conf={self.confidence:.2f}>"


class FaceReference(Base):
    """
    High-quality reference frame for identity consistency.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "face_references"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    analysis_id = Column(String(50), ForeignKey("vision_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(String(50), ForeignKey("detected_subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(Float, nullable=False)
    quality_score = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    analysis = relationship("VisionAnalysis", back_populates="face_references")
    subject = relationship("DetectedSubject", back_populates="face_references")
    media_file = relationship("MediaFile")

    def __repr__(self) -> str:
        return f"<FaceReference id={self.id} media_id={self.media_file_id} t={self.timestamp:.2f}s score={self.quality_score:.2f}>"


class PoseDetection(Base):
    """
    Body pose estimation instance for a subject at a timestamp.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "pose_detections"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    subject_id = Column(String(50), ForeignKey("detected_subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(Float, nullable=False, index=True)
    frame_reference = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    subject = relationship("DetectedSubject", back_populates="pose_detections")
    landmarks = relationship(
        "PoseLandmark",
        back_populates="pose_detection",
        cascade="all, delete-orphan",
        order_by="PoseLandmark.landmark_index",
    )

    def __repr__(self) -> str:
        return f"<PoseDetection id={self.id} t={self.timestamp:.2f}s conf={self.confidence:.2f}>"


class PoseLandmark(Base):
    """
    Individual keypoint/landmark of body pose.
    Phase 8: Face Detection + Identity Reference + Pose Tracking
    """
    __tablename__ = "pose_landmarks"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    pose_detection_id = Column(String(50), ForeignKey("pose_detections.id", ondelete="CASCADE"), nullable=False, index=True)
    landmark_index = Column(Integer, nullable=False)
    landmark_name = Column(String(50), nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    z = Column(Float, nullable=False, default=0.0)
    visibility = Column(Float, nullable=False, default=1.0)

    pose_detection = relationship("PoseDetection", back_populates="landmarks")

    def __repr__(self) -> str:
        return f"<PoseLandmark #{self.landmark_index} {self.landmark_name} ({self.x:.2f},{self.y:.2f}) vis={self.visibility:.2f}>"


class ComicGeneration(Base):
    """
    3D Comic style visual generation run for a project.
    Phase 9: 3D Comic Style Generation
    """
    __tablename__ = "comic_generations"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False, default="openai")
    model = Column(String(50), nullable=False, default="dall-e-3")
    status = Column(String(30), nullable=False, default="queued", index=True)  # queued, processing, completed, failed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="comic_generations")
    frames = relationship(
        "ComicFrame",
        back_populates="generation",
        cascade="all, delete-orphan",
        order_by="ComicFrame.timestamp",
    )

    def __repr__(self) -> str:
        return f"<ComicGeneration id={self.id} project_id={self.project_id} provider='{self.provider}' model='{self.model}' status='{self.status}'>"


class ComicFrame(Base):
    """
    Individual generated 3D comic visual frame corresponding to a scene/keyframe.
    Phase 9: 3D Comic Style Generation
    """
    __tablename__ = "comic_frames"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    generation_id = Column(String(50), ForeignKey("comic_generations.id", ondelete="CASCADE"), nullable=False, index=True)
    scene_id = Column(String(50), ForeignKey("video_scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    source_keyframe_id = Column(String(50), ForeignKey("scene_keyframes.id", ondelete="SET NULL"), nullable=True, index=True)
    output_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=True, index=True)
    timestamp = Column(Float, nullable=False, default=0.0)
    width = Column(Integer, nullable=False, default=1024)
    height = Column(Integer, nullable=False, default=1792)
    prompt_version = Column(String(50), nullable=True)
    status = Column(String(30), nullable=False, default="processing", index=True)  # processing, completed, failed
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    generation = relationship("ComicGeneration", back_populates="frames")
    scene = relationship("VideoScene")
    source_keyframe = relationship("SceneKeyframe")
    output_media_file = relationship("MediaFile")

    def __repr__(self) -> str:
        return f"<ComicFrame id={self.id} gen_id={self.generation_id} scene={self.scene_id} t={self.timestamp:.2f}s status='{self.status}'>"


class CharacterConsistencyProfile(Base):
    """
    Project-local character consistency profile for the primary subject.
    Phase 10: Identity + Temporal Consistency Engine
    """
    __tablename__ = "character_consistency_profiles"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(String(50), ForeignKey("detected_subjects.id", ondelete="SET NULL"), nullable=True, index=True)
    canonical_reference_id = Column(String(50), ForeignKey("face_references.id", ondelete="SET NULL"), nullable=True, index=True)
    style_version = Column(String(50), nullable=False, default="v1-3d-comic-lock")
    profile_version = Column(String(50), nullable=False, default="v1.0")
    descriptor_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="consistency_profiles")
    subject = relationship("DetectedSubject")
    canonical_reference = relationship("FaceReference")
    generations = relationship(
        "ConsistencyGeneration",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="desc(ConsistencyGeneration.created_at)",
    )

    def __repr__(self) -> str:
        return f"<CharacterConsistencyProfile id={self.id} project_id={self.project_id} style='{self.style_version}'>"


class ConsistencyGeneration(Base):
    """
    Identity and temporal consistency generation run across scenes.
    Phase 10: Identity + Temporal Consistency Engine
    """
    __tablename__ = "consistency_generations"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_id = Column(String(50), ForeignKey("character_consistency_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(50), nullable=False, default="openai")
    model = Column(String(50), nullable=False, default="dall-e-3")
    status = Column(String(30), nullable=False, default="queued", index=True)  # queued, processing, completed, failed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="consistency_generations")
    profile = relationship("CharacterConsistencyProfile", back_populates="generations")
    frames = relationship(
        "ConsistentComicFrame",
        back_populates="generation",
        cascade="all, delete-orphan",
        order_by="ConsistentComicFrame.sequence",
    )

    def __repr__(self) -> str:
        return f"<ConsistencyGeneration id={self.id} project_id={self.project_id} provider='{self.provider}' status='{self.status}'>"


class ConsistentComicFrame(Base):
    """
    Individual identity-consistent and temporally coherent 3D comic visual frame.
    Phase 10: Identity + Temporal Consistency Engine
    """
    __tablename__ = "consistent_comic_frames"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    consistency_generation_id = Column(String(50), ForeignKey("consistency_generations.id", ondelete="CASCADE"), nullable=False, index=True)
    scene_id = Column(String(50), ForeignKey("video_scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    source_comic_frame_id = Column(String(50), ForeignKey("comic_frames.id", ondelete="SET NULL"), nullable=True, index=True)
    output_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False, default=0)
    previous_frame_id = Column(String(50), ForeignKey("consistent_comic_frames.id", ondelete="SET NULL"), nullable=True, index=True)
    timestamp = Column(Float, nullable=False, default=0.0)
    width = Column(Integer, nullable=False, default=1024)
    height = Column(Integer, nullable=False, default=1792)
    prompt_version = Column(String(50), nullable=True)
    diagnostics = Column(JSON, nullable=True)
    status = Column(String(30), nullable=False, default="processing", index=True)  # processing, completed, failed
    error_code = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    generation = relationship("ConsistencyGeneration", back_populates="frames")
    scene = relationship("VideoScene")
    source_comic_frame = relationship("ComicFrame")
    output_media_file = relationship("MediaFile")
    previous_frame = relationship("ConsistentComicFrame", remote_side=[id])

    def __repr__(self) -> str:
        return f"<ConsistentComicFrame id={self.id} seq={self.sequence} scene={self.scene_id} status='{self.status}'>"


class SegmentationResult(Base):
    """
    Foreground segmentation, alpha matting, and layered background scene.
    Phase 11: Foreground Segmentation + Dynamic Background
    """
    __tablename__ = "segmentation_results"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    consistent_frame_id = Column(String(50), ForeignKey("consistent_comic_frames.id", ondelete="SET NULL"), nullable=True, index=True)
    source_comic_frame_id = Column(String(50), ForeignKey("comic_frames.id", ondelete="SET NULL"), nullable=True, index=True)
    source_scene_id = Column(String(50), ForeignKey("video_scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    source_keyframe_id = Column(String(50), ForeignKey("scene_keyframes.id", ondelete="SET NULL"), nullable=True, index=True)
    provider = Column(String(50), nullable=False, default="opencv_guided")
    model = Column(String(50), nullable=False, default="grabcut_pose_prior")
    status = Column(String(30), nullable=False, default="processing", index=True)  # queued, processing, completed, review_required, failed
    background_mode = Column(String(50), nullable=False, default="ORIGINAL")  # ORIGINAL, SOFT_BLUR, DEPTH_STYLE, COMIC_STYLE

    mask_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)
    foreground_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)
    background_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)
    composite_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)

    bbox_x = Column(Float, nullable=True)
    bbox_y = Column(Float, nullable=True)
    bbox_width = Column(Float, nullable=True)
    bbox_height = Column(Float, nullable=True)

    quality_metrics = Column(JSON, nullable=True)
    error_code = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="segmentation_results")
    consistent_frame = relationship("ConsistentComicFrame")
    source_comic_frame = relationship("ComicFrame")
    source_scene = relationship("VideoScene")
    source_keyframe = relationship("SceneKeyframe")
    mask_media = relationship("MediaFile", foreign_keys=[mask_media_file_id])
    foreground_media = relationship("MediaFile", foreign_keys=[foreground_media_file_id])
    background_media = relationship("MediaFile", foreign_keys=[background_media_file_id])
    composite_media = relationship("MediaFile", foreign_keys=[composite_media_file_id])

    def __repr__(self) -> str:
        return f"<SegmentationResult id={self.id} project_id={self.project_id} frame={self.consistent_frame_id} status='{self.status}' mode='{self.background_mode}'>"


class LyricStyle(Base):
    """
    Visual styling configuration for kinetic lyric rendering.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    __tablename__ = "lyric_styles"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False, index=True)
    font_family = Column(String(100), nullable=False, default="Outfit")
    font_size = Column(Integer, nullable=False, default=64)
    font_weight = Column(String(30), nullable=False, default="bold")
    fill_color = Column(String(50), nullable=False, default="#FFFFFF")
    outline_color = Column(String(50), nullable=True, default="#000000")
    outline_width = Column(Integer, nullable=False, default=4)
    shadow_color = Column(String(50), nullable=True, default="rgba(0,0,0,0.8)")
    shadow_offset_x = Column(Integer, nullable=False, default=4)
    shadow_offset_y = Column(Integer, nullable=False, default=4)
    shadow_blur = Column(Integer, nullable=False, default=8)
    letter_spacing = Column(Integer, nullable=False, default=2)
    line_spacing = Column(Float, nullable=False, default=1.15)
    text_transform = Column(String(30), nullable=False, default="uppercase")
    alignment = Column(String(20), nullable=False, default="center")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="lyric_styles")

    def __repr__(self) -> str:
        return f"<LyricStyle id={self.id} name='{self.name}' font='{self.font_family}' fill='{self.fill_color}'>"


class LyricAnimation(Base):
    """
    Animation preset defining motion curves and timing for lyrics.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    __tablename__ = "lyric_animations"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(50), nullable=False, index=True)
    animation_type = Column(String(50), nullable=False, default="POP")
    duration = Column(Float, nullable=False, default=0.35)
    easing = Column(String(50), nullable=False, default="ease_out_back")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="lyric_animations")

    def __repr__(self) -> str:
        return f"<LyricAnimation id={self.id} name='{self.name}' type='{self.animation_type}' dur={self.duration}s>"


class LyricSegment(Base):
    """
    Displayable lyric and kinetic text segment with positioning and layer order.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    __tablename__ = "lyric_segments"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    transcript_segment_id = Column(String(50), ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True, index=True)
    style_id = Column(String(50), ForeignKey("lyric_styles.id", ondelete="SET NULL"), nullable=True, index=True)
    animation_id = Column(String(50), ForeignKey("lyric_animations.id", ondelete="SET NULL"), nullable=True, index=True)
    sequence = Column(Integer, nullable=False, default=0, index=True)
    start_time = Column(Float, nullable=False, index=True)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    position_x = Column(Float, nullable=False, default=0.5)
    position_y = Column(Float, nullable=False, default=0.75)
    scale = Column(Float, nullable=False, default=1.0)
    rotation = Column(Float, nullable=False, default=0.0)
    opacity = Column(Float, nullable=False, default=1.0)
    z_layer = Column(Integer, nullable=False, default=1)  # 0=background, 1=text behind character, 2=foreground character
    enabled = Column(Boolean, nullable=False, default=True)
    words_data = Column(Text, nullable=True)  # JSON-encoded word timestamps if available from transcript
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="lyric_segments")
    transcript_segment = relationship("TranscriptSegment")
    style = relationship("LyricStyle")
    animation = relationship("LyricAnimation")
    previews = relationship(
        "LyricPreview",
        back_populates="lyric_segment",
        cascade="all, delete-orphan",
        order_by="desc(LyricPreview.created_at)",
    )

    def __repr__(self) -> str:
        return f"<LyricSegment id={self.id} seq={self.sequence} [{self.start_time:.2f}-{self.end_time:.2f}] text='{self.text[:20]}'>"


class LyricPreview(Base):
    """
    Rendered composite preview frame showing text-behind-character composition.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    __tablename__ = "lyric_previews"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    lyric_segment_id = Column(String(50), ForeignKey("lyric_segments.id", ondelete="SET NULL"), nullable=True, index=True)
    scene_id = Column(String(50), ForeignKey("video_scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    segmentation_id = Column(String(50), ForeignKey("segmentation_results.id", ondelete="SET NULL"), nullable=True, index=True)
    timestamp = Column(Float, nullable=False, index=True)
    output_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, index=True)
    compositing_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    project = relationship("Project", back_populates="lyric_previews")
    lyric_segment = relationship("LyricSegment", back_populates="previews")
    scene = relationship("VideoScene")
    segmentation = relationship("SegmentationResult")
    output_media_file = relationship("MediaFile")

    def __repr__(self) -> str:
        return f"<LyricPreview id={self.id} project_id={self.project_id} t={self.timestamp:.2f}s>"


class RenderJob(Base):
    """
    Final video render job producing vertical 9:16 MP4 reel.
    Phase 13: Final Video Compositing + 9:16 Reel Rendering
    """
    __tablename__ = "render_jobs"

    id = Column(String(50), primary_key=True, default=generate_uuid, index=True)
    project_id = Column(String(50), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_media_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="queued", index=True)  # queued, processing, completed, failed, cancelled
    width = Column(Integer, nullable=False, default=1080)
    height = Column(Integer, nullable=False, default=1920)
    fps = Column(Float, nullable=False, default=30.0)
    video_codec = Column(String(50), nullable=False, default="libx264")
    audio_codec = Column(String(50), nullable=False, default="aac")
    duration = Column(Float, nullable=True)
    output_media_file_id = Column(String(50), ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True, index=True)
    progress = Column(Float, nullable=False, default=0.0)  # 0.0 to 1.0
    stage_message = Column(String(255), nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    render_config = Column(JSON, nullable=True)
    render_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="render_jobs")
    source_media = relationship("MediaFile", foreign_keys=[source_media_id])
    output_media = relationship("MediaFile", foreign_keys=[output_media_file_id])

    def __repr__(self) -> str:
        return f"<RenderJob id={self.id} project_id={self.project_id} status='{self.status}' progress={self.progress:.2f}>"



