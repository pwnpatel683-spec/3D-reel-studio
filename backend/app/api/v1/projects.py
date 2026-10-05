"""
3D Reel Studio — Projects API Endpoints
Phase 3, Phase 4 & Phase 5: Project Session Persistence, Media Storage & Audio Extraction
"""

import json
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload
from app.core.logging import logger
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.project import (
    Project,
    MediaFile,
    Transcript,
    TranscriptSegment,
    VideoAnalysis,
    VideoScene,
    SceneKeyframe,
    VisionAnalysis,
    DetectedSubject,
    FaceDetection,
    FaceReference,
    PoseDetection,
    PoseLandmark,
    ComicGeneration,
    ComicFrame,
    CharacterConsistencyProfile,
    ConsistencyGeneration,
    ConsistentComicFrame,
    SegmentationResult,
    LyricStyle,
    LyricAnimation,
    LyricSegment,
    LyricPreview,
    RenderJob,
    generate_uuid,
)
from app.schemas.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectSummary,
    ProjectDetail,
    MediaFileSummary,
    MediaUploadResponse,
    TranscriptResponse,
    TranscriptDetail,
    TranscriptSegmentSummary,
    WordTimestamp,
    KeyframeSummary,
    VideoSceneSummary,
    VideoAnalysisDetail,
    VideoAnalysisResponse,
    VisionAnalysisDetail,
    VisionAnalysisResponse,
    ComicGenerationRequest,
    ComicFrameSummary,
    ComicGenerationDetail,
    ComicGenerationResponse,
    CharacterConsistencyProfileDetail,
    ConsistencyProfileResponse,
    ConsistencyGenerationRequest,
    ConsistentComicFrameSummary,
    ConsistencyGenerationDetail,
    ConsistencyGenerationResponse,
    SegmentationRequest,
    SegmentationResultDetail,
    SegmentationResponse,
    LyricStyleSummary,
    LyricAnimationSummary,
    LyricSegmentSummary,
    LyricSegmentUpdate,
    LyricSyncRequest,
    LyricSyncResponse,
    LyricPreviewRequest,
    LyricPreviewDetail,
    LyricPreviewResponse,
    LyricListResponse,
    RenderJobRequest,
    RenderJobSummary,
    RenderJobResponse,
    RenderJobListResponse,
    StorageAuditResponse,
    StorageCleanupRequest,
    StorageCleanupResponse,
)
from app.services.storage import (
    get_base_storage_dir,
    get_project_storage_dir,
    validate_media_upload,
    generate_stored_filename,
    save_upload_file_chunked,
)
from app.services.audio import (
    get_project_audio_dir,
    extract_audio_from_video,
)
from app.services.transcription import (
    transcribe_audio_file,
)
from app.services.analysis import (
    analyze_video_pipeline,
)
from app.services.vision import (
    run_vision_analysis_pipeline,
)
from app.services.comic_generation import (
    run_comic_generation_pipeline,
)
from app.services.consistency import (
    CharacterConsistencyService,
    run_consistency_generation_pipeline,
)
from app.services.segmentation import (
    run_segmentation_pipeline,
)
from app.services.lyrics import (
    get_or_create_default_styles,
    get_or_create_default_animations,
    sync_transcript_to_lyrics,
    generate_lyric_preview,
)
from app.services.render import (
    run_final_reel_render_sync,
    cancel_render_job,
)
from app.services.maintenance import (
    audit_project_storage,
    cleanup_project_storage,
)


router = APIRouter(prefix="/projects", tags=["Studio Projects"])


def get_owned_project(
    project_id: str,
    current_user: User,
    db: Session,
    load_all: bool = False,
) -> Project:
    """
    Retrieves a project by ID and strictly enforces user ownership.
    If the project does not exist or belongs to another user, raises 404 Not Found
    to prevent ID enumeration and metadata leakage.
    """
    clean_id = project_id.strip()
    if (
        not clean_id
        or ".." in clean_id
        or "/" in clean_id
        or "\\" in clean_id
        or clean_id.startswith(".")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PROJECT_ID", "message": "Invalid project identifier (path traversal prohibited)."},
        )

    query = db.query(Project)
    if load_all:
        query = query.options(
            selectinload(Project.media_files),
            selectinload(Project.transformation_jobs),
            selectinload(Project.transcripts).selectinload(Transcript.segments),
            selectinload(Project.video_analyses).selectinload(VideoAnalysis.scenes).selectinload(VideoScene.keyframes),
            selectinload(Project.vision_analyses)
            .selectinload(VisionAnalysis.subjects)
            .selectinload(DetectedSubject.face_detections),
            selectinload(Project.vision_analyses)
            .selectinload(VisionAnalysis.subjects)
            .selectinload(DetectedSubject.pose_detections)
            .selectinload(PoseDetection.landmarks),
            selectinload(Project.vision_analyses).selectinload(VisionAnalysis.face_references),
            selectinload(Project.comic_generations).selectinload(ComicGeneration.frames),
            selectinload(Project.consistency_profiles),
            selectinload(Project.consistency_generations).selectinload(ConsistencyGeneration.frames),
            selectinload(Project.segmentation_results),
            selectinload(Project.lyric_styles),
            selectinload(Project.lyric_animations),
            selectinload(Project.lyric_segments),
            selectinload(Project.lyric_previews),
            selectinload(Project.render_jobs),
        )
    project = query.filter(Project.id == clean_id, Project.user_id == current_user.id).first()
    if not project:
        logger.warning(f"Project lookup failed or unauthorized: ProjectID='{clean_id}', UserID='{current_user.id}'")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' not found.",
        )
    return project



@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new studio project",
    description="Creates a new persistent 3D Reel project session in draft status.",
)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """
    Creates a new project record in the database.
    """
    try:
        new_project = Project(
            name=payload.name,
            status="draft",
            user_id=current_user.id,
        )
        db.add(new_project)
        db.commit()
        db.refresh(new_project)

        logger.info(f"Project created: ID='{new_project.id}', Name='{new_project.name}'")
        return ProjectResponse(
            success=True,
            project=ProjectSummary.model_validate(new_project),
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project in database.",
        )


@router.get(
    "",
    response_model=ProjectListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all studio projects",
    description="Retrieves a list of all studio projects ordered by creation date (newest first).",
)
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectListResponse:
    """
    Returns all projects ordered by newest first for authenticated user.
    """
    try:
        projects = db.query(Project).filter(Project.user_id == current_user.id).order_by(Project.created_at.desc()).all()
        project_summaries = [ProjectSummary.model_validate(p) for p in projects]
        return ProjectListResponse(
            success=True,
            projects=project_summaries,
            count=len(project_summaries),
        )
    except Exception as e:
        logger.error(f"Error listing projects: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve projects from database.",
        )


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve complete project state",
    description="Retrieves project details along with all associated media files and transformation jobs.",
)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectDetailResponse:
    """
    Retrieves project by ID with eager-loaded relationships including uploaded media.
    """
    project = get_owned_project(project_id, current_user, db, load_all=True)

    return ProjectDetailResponse(
        success=True,
        project=ProjectDetail.model_validate(project),
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update project details",
    description="Allows updating project name or status.",
)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """
    Updates mutable project attributes.
    """
    clean_id = project_id.strip()
    project = get_owned_project(clean_id, current_user, db)

    try:
        updated = False
        if payload.name is not None:
            project.name = payload.name
            updated = True
        if payload.status is not None:
            project.status = payload.status
            updated = True

        if updated:
            db.commit()
            db.refresh(project)
            logger.info(f"Project updated: ID='{project.id}', Name='{project.name}', Status='{project.status}'")

        return ProjectResponse(
            success=True,
            project=ProjectSummary.model_validate(project),
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating project '{clean_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project in database.",
        )


@router.post(
    "/{project_id}/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload media file to project",
    description="Uploads and securely stores a source video or face reference image for a project.",
)
async def upload_project_media(
    project_id: str,
    file: UploadFile = File(..., description="Multipart binary media file"),
    media_type: str = Form(..., description="Target media type: 'source_video' or 'face_reference'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MediaUploadResponse:
    """
    Validates, streams, and securely stores uploaded media, creating a persistent MediaFile record.
    """
    clean_id = project_id.strip()
    project = get_owned_project(clean_id, current_user, db)

    # 2. Validate media_type, file extension, MIME type, and determine max size limit
    ext, max_bytes = validate_media_upload(
        filename=file.filename,
        content_type=file.content_type,
        media_type=media_type,
    )

    clean_media_type = media_type.strip().lower()

    # 3. Resolve secure target storage directory (enforcing path traversal protection)
    target_dir = get_project_storage_dir(clean_id, clean_media_type)
    stored_filename = generate_stored_filename(ext)
    target_file_path = target_dir / stored_filename

    # 4. Stream and write file chunk by chunk, calculating SHA-256 hash simultaneously
    total_bytes, sha256_hex = await save_upload_file_chunked(
        upload_file=file,
        target_path=target_file_path,
        max_bytes=max_bytes,
    )

    # 5. Persist MediaFile record in SQLite database
    sub_dir_name = "source" if clean_media_type == "source_video" else "face-reference"
    relative_path = f"projects/{clean_id}/{sub_dir_name}/{stored_filename}"
    original_name = Path(file.filename or "media").name

    media_record = MediaFile(
        id=generate_uuid(),
        project_id=clean_id,
        file_type=clean_media_type,
        original_filename=original_name,
        stored_filename=stored_filename,
        file_path=relative_path,
        mime_type=file.content_type or ("video/mp4" if clean_media_type == "source_video" else "image/jpeg"),
        file_size=total_bytes,
        sha256_hash=sha256_hex,
    )

    try:
        db.add(media_record)
        if project.status == "draft":
            project.status = "uploaded"
        db.commit()
        db.refresh(media_record)
        logger.info(
            f"Media file saved: ID='{media_record.id}', Project='{clean_id}', Type='{clean_media_type}', "
            f"Original='{original_name}', Stored='{stored_filename}', Size={total_bytes}B, SHA256={sha256_hex[:8]}..."
        )
    except Exception as e:
        db.rollback()
        # Clean up created physical file if database commit fails
        if target_file_path.exists():
            try:
                target_file_path.unlink()
            except Exception:
                pass
        logger.error(f"Failed to record media file in database for project '{clean_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist media file metadata to database.",
        )

    return MediaUploadResponse(
        success=True,
        media=MediaFileSummary.model_validate(media_record),
    )


@router.get(
    "/{project_id}/media/{media_id}/download",
    summary="Download or stream project media file",
    description="Securely streams or downloads a validated project media file. Enforces strict path traversal and project isolation.",
)
@router.get(
    "/{project_id}/media/{media_id}",
    summary="Stream project media file",
    description="Securely streams or previews a validated project media file.",
)
async def download_project_media(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """
    Securely serves a validated media file belonging to a project.
    Guarantees users cannot escape storage root via path traversal or access unauthorized files.
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # 1. Verify project exists and belongs to current authenticated user
    project = get_owned_project(clean_project_id, current_user, db)

    # 2. Verify media file record exists and belongs to project
    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id, MediaFile.project_id == project.id).first()
    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDIA_NOT_FOUND", "message": f"Media file '{clean_media_id}' not found."},
        )

    # 4. Resolve physical file path securely
    base_storage = get_base_storage_dir()
    p = Path(media.file_path)
    if not p.is_absolute():
        p = base_storage / media.file_path

    try:
        resolved = p.resolve()
        # Ensure path stays strictly inside base storage directory
        if not str(resolved).startswith(str(base_storage.resolve())):
            logger.warning(f"Path traversal attempt prevented during download: '{media.file_path}'")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_PATH", "message": "Invalid media storage path."},
            )
    except Exception as e:
        logger.error(f"Security error resolving media file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PATH", "message": "Could not resolve media path."},
        )

    if not resolved.is_file():
        logger.error(f"Physical media file missing on disk: {resolved}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FILE_NOT_FOUND", "message": "Media file missing from storage disk."},
        )

    mime_type = media.mime_type or "application/octet-stream"
    return FileResponse(
        path=str(resolved),
        media_type=mime_type,
        filename=media.original_filename or resolved.name,
    )


@router.post(
    "/{project_id}/media/{media_id}/extract-audio",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Extract audio track from source video",
    description="Transcodes and extracts the audio track from an uploaded source video to MP3 format using FFmpeg.",
)
async def extract_project_audio(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MediaUploadResponse:
    """
    Extracts the audio track from an uploaded source video and creates an extracted_audio MediaFile.
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # 1. Verify project ownership
    project = get_owned_project(clean_project_id, current_user, db)
    # 2. Verify media exists
    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id).first()
    if not media:
        logger.warning(f"Audio extraction failed: Media '{clean_media_id}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media file with ID '{clean_media_id}' not found.",
        )

    # 3. Verify media belongs to project
    if media.project_id != clean_project_id:
        logger.warning(
            f"Audio extraction rejected: Media '{clean_media_id}' belongs to '{media.project_id}', not '{clean_project_id}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Media file '{clean_media_id}' does not belong to project '{clean_project_id}'.",
        )

    # 4. Verify media is a source video
    if media.file_type != "source_video":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Media file is not a source video (type: '{media.file_type}'). Audio can only be extracted from source videos.",
        )

    # 5. Verify physical source file exists on disk
    base_storage = get_base_storage_dir()
    source_file_path = base_storage / media.file_path
    if not source_file_path.exists() or not source_file_path.is_file():
        logger.error(f"Source video physical file missing on disk: {source_file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source video physical file is missing from storage.",
        )

    # 6. Prepare target audio destination directory and unique filename
    audio_dir = get_project_audio_dir(clean_project_id)
    stored_filename = generate_stored_filename(".mp3")
    target_audio_path = audio_dir / stored_filename

    # 7. Execute FFmpeg extraction
    file_size, sha256_hex = extract_audio_from_video(
        source_video_path=source_file_path,
        output_audio_path=target_audio_path,
    )

    # 8. Create MediaFile record in SQLite
    relative_audio_path = f"projects/{clean_project_id}/audio/{stored_filename}"
    orig_stem = Path(media.original_filename).stem
    orig_audio_name = f"{orig_stem}_audio.mp3"

    audio_record = MediaFile(
        id=generate_uuid(),
        project_id=clean_project_id,
        file_type="extracted_audio",
        original_filename=orig_audio_name,
        stored_filename=stored_filename,
        file_path=relative_audio_path,
        mime_type="audio/mpeg",
        file_size=file_size,
        sha256_hash=sha256_hex,
    )

    try:
        db.add(audio_record)
        db.commit()
        db.refresh(audio_record)
        logger.info(
            f"Extracted audio saved: ID='{audio_record.id}', Project='{clean_project_id}', "
            f"Original='{orig_audio_name}', Stored='{stored_filename}', Size={file_size}B"
        )
    except Exception as e:
        db.rollback()
        # Clean up generated audio file on database error
        if target_audio_path.exists():
            target_audio_path.unlink(missing_ok=True)
        logger.error(f"Failed to record extracted audio in database: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist extracted audio metadata to database.",
        )

    return MediaUploadResponse(
        success=True,
        media=MediaFileSummary.model_validate(audio_record),
    )


@router.post(
    "/{project_id}/media/{media_id}/transcribe",
    response_model=TranscriptResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe extracted audio to timestamped segments",
    description="Processes an extracted audio file using OpenAI's transcription API and persists timestamped segments.",
)
async def transcribe_media(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TranscriptResponse:
    """
    Transcribes project audio and stores the resulting timestamped transcript.
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # 1. Verify project ownership
    project = get_owned_project(clean_project_id, current_user, db)
    # 2. Verify media exists
    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id).first()
    if not media:
        logger.warning(f"Transcription failed: Media '{clean_media_id}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MEDIA_NOT_FOUND",
                "message": f"Media file with ID '{clean_media_id}' not found.",
            },
        )

    # 3. Verify media belongs to project
    if media.project_id != clean_project_id:
        logger.warning(
            f"Transcription rejected: Media '{clean_media_id}' belongs to '{media.project_id}', not '{clean_project_id}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEDIA_PROJECT_MISMATCH",
                "message": f"Media file '{clean_media_id}' does not belong to project '{clean_project_id}'.",
            },
        )

    # 4. Verify media is extracted audio
    if media.file_type != "extracted_audio":
        logger.warning(f"Transcription rejected: Media '{clean_media_id}' is '{media.file_type}', not 'extracted_audio'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_MEDIA_TYPE",
                "message": f"Media file is not an extracted audio track (type: '{media.file_type}'). Only extracted audio can be transcribed.",
            },
        )

    # 5. Verify physical audio file exists on disk
    base_storage = get_base_storage_dir()
    audio_file_path = base_storage / media.file_path
    if not audio_file_path.exists() or not audio_file_path.is_file():
        logger.error(f"Extracted audio physical file missing on disk: {audio_file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "AUDIO_FILE_NOT_FOUND",
                "message": "Physical audio file is missing from storage.",
            },
        )

    # 6. Execute transcription via service
    result = transcribe_audio_file(audio_path=audio_file_path)

    # 7. Persist Transcript and TranscriptSegments in SQLite
    transcript_id = generate_uuid()
    transcript_record = Transcript(
        id=transcript_id,
        project_id=clean_project_id,
        audio_media_id=clean_media_id,
        language=result.language,
        full_text=result.full_text,
    )

    segment_records: List[TranscriptSegment] = []
    for seg in result.segments:
        words_json = None
        if seg.words:
            words_json = json.dumps([
                {"word": w.word, "start_time": w.start_time, "end_time": w.end_time}
                for w in seg.words
            ])

        segment_records.append(
            TranscriptSegment(
                id=generate_uuid(),
                transcript_id=transcript_id,
                sequence=seg.sequence,
                start_time=seg.start_time,
                end_time=seg.end_time,
                text=seg.text,
                words_data=words_json,
            )
        )

    try:
        db.add(transcript_record)
        db.add_all(segment_records)
        db.commit()
        db.refresh(transcript_record)
        logger.info(
            f"Transcript saved: ID='{transcript_record.id}', Project='{clean_project_id}', "
            f"Language='{transcript_record.language}', Segments={len(segment_records)}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to persist transcript in database: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "DATABASE_PERSISTENCE_FAILED",
                "message": "Failed to persist transcript records to the database.",
            },
        )

    # Re-fetch transcript with segments eager loaded for consistent response serialization
    eager_transcript = (
        db.query(Transcript)
        .options(selectinload(Transcript.segments))
        .filter(Transcript.id == transcript_id)
        .first()
    )

    return TranscriptResponse(
        success=True,
        transcript=TranscriptDetail.model_validate(eager_transcript or transcript_record),
    )


@router.post(
    "/{project_id}/media/{media_id}/analyze",
    response_model=VideoAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze video metadata, scenes, and keyframes",
    description="Extracts stream metadata, detects scene/shot boundaries, and extracts representative keyframe images.",
)
async def analyze_media(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VideoAnalysisResponse:
    """
    Analyzes an uploaded video file, detecting shot boundaries and extracting keyframes.
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # 1. Verify project ownership
    project = get_owned_project(clean_project_id, current_user, db)
    # 2. Verify media exists
    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id).first()
    if not media:
        logger.warning(f"Video analysis failed: Media '{clean_media_id}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MEDIA_NOT_FOUND",
                "message": f"Media file with ID '{clean_media_id}' not found.",
            },
        )

    # 3. Verify media belongs to project
    if media.project_id != clean_project_id:
        logger.warning(
            f"Video analysis rejected: Media '{clean_media_id}' belongs to '{media.project_id}', not '{clean_project_id}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEDIA_PROJECT_MISMATCH",
                "message": f"Media file '{clean_media_id}' does not belong to project '{clean_project_id}'.",
            },
        )

    # 4. Verify media is a supported video type
    if media.file_type != "source_video":
        logger.warning(f"Video analysis rejected: Media '{clean_media_id}' is '{media.file_type}', not 'source_video'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_MEDIA_TYPE",
                "message": f"Media file is not a source video (type: '{media.file_type}'). Only source videos can be analyzed for scenes.",
            },
        )

    # 5. Verify physical source video exists on disk
    base_storage = get_base_storage_dir()
    video_file_path = base_storage / media.file_path
    if not video_file_path.exists() or not video_file_path.is_file():
        logger.error(f"Source video physical file missing on disk: {video_file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "VIDEO_FILE_NOT_FOUND",
                "message": "Physical video file is missing from storage.",
            },
        )

    # 6. Idempotency: Clean up previous analysis and orphaned keyframes for this source media if re-analyzing
    existing_analyses = (
        db.query(VideoAnalysis)
        .options(selectinload(VideoAnalysis.scenes).selectinload(VideoScene.keyframes))
        .filter(VideoAnalysis.source_media_id == clean_media_id)
        .all()
    )
    for old_analysis in existing_analyses:
        for old_scene in old_analysis.scenes:
            for old_kf in old_scene.keyframes:
                old_media_record = db.query(MediaFile).filter(MediaFile.id == old_kf.media_file_id).first()
                if old_media_record:
                    old_path = base_storage / old_media_record.file_path
                    if old_path.exists():
                        try:
                            old_path.unlink()
                        except Exception:
                            pass
                    db.delete(old_media_record)
        db.delete(old_analysis)
    db.commit()

    # 7. Run Analysis Pipeline
    result = analyze_video_pipeline(
        project_id=clean_project_id,
        video_path=video_file_path,
    )

    # 8. Persist Database Records
    analysis_id = generate_uuid()
    analysis_record = VideoAnalysis(
        id=analysis_id,
        project_id=clean_project_id,
        source_media_id=clean_media_id,
        width=result.metadata.width,
        height=result.metadata.height,
        fps=result.metadata.fps,
        frame_count=result.metadata.frame_count,
        duration=result.metadata.duration,
        codec=result.metadata.codec,
        pixel_format=result.metadata.pixel_format,
        aspect_ratio=result.metadata.aspect_ratio,
    )

    scene_records: List[VideoScene] = []
    keyframe_media_records: List[MediaFile] = []
    keyframe_records: List[SceneKeyframe] = []

    for s_data in result.scenes:
        scene_id = generate_uuid()
        scene_record = VideoScene(
            id=scene_id,
            analysis_id=analysis_id,
            sequence=s_data.sequence,
            start_time=s_data.start_time,
            end_time=s_data.end_time,
            duration=s_data.duration,
        )
        scene_records.append(scene_record)

        if s_data.keyframe:
            kf = s_data.keyframe
            kf_media_id = generate_uuid()
            kf_media = MediaFile(
                id=kf_media_id,
                project_id=clean_project_id,
                file_type="keyframe_image",
                original_filename=f"scene_{s_data.sequence}_keyframe.jpg",
                stored_filename=kf.stored_filename,
                file_path=kf.relative_path,
                mime_type="image/jpeg",
                file_size=kf.file_size,
                sha256_hash=kf.sha256_hash,
            )
            keyframe_media_records.append(kf_media)

            kf_record = SceneKeyframe(
                id=generate_uuid(),
                scene_id=scene_id,
                timestamp=kf.timestamp,
                media_file_id=kf_media_id,
                width=kf.width,
                height=kf.height,
            )
            keyframe_records.append(kf_record)

    try:
        db.add(analysis_record)
        db.add_all(scene_records)
        db.add_all(keyframe_media_records)
        db.add_all(keyframe_records)
        db.commit()
        db.refresh(analysis_record)
        logger.info(
            f"Video analysis saved: ID='{analysis_record.id}', Project='{clean_project_id}', "
            f"Scenes={len(scene_records)}, Keyframes={len(keyframe_records)}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to persist video analysis in database: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "DATABASE_PERSISTENCE_FAILED",
                "message": "Failed to persist video analysis records to the database.",
            },
        )

    # Re-fetch analysis with scenes and keyframes eager loaded
    eager_analysis = (
        db.query(VideoAnalysis)
        .options(selectinload(VideoAnalysis.scenes).selectinload(VideoScene.keyframes))
        .filter(VideoAnalysis.id == analysis_id)
        .first()
    )

    return VideoAnalysisResponse(
        success=True,
        analysis=VideoAnalysisDetail.model_validate(eager_analysis or analysis_record),
    )


@router.post(
    "/{project_id}/media/{media_id}/vision-analysis",
    response_model=VisionAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze human faces, primary subject identity, and body pose tracking",
    description="Detects human faces, extracts facial landmarks, tracks subjects temporally, identifies primary person, extracts quality face references, and estimates 17-point body pose.",
)
async def analyze_vision(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisionAnalysisResponse:
    """
    Executes computer vision analysis extracting face detections, primary person reference crops, and pose tracking.
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # 1. Verify project ownership
    project = get_owned_project(clean_project_id, current_user, db)
    # 2. Verify media exists
    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id).first()
    if not media:
        logger.warning(f"Vision analysis failed: Media '{clean_media_id}' not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MEDIA_NOT_FOUND",
                "message": f"Media file with ID '{clean_media_id}' not found.",
            },
        )

    # 3. Verify media belongs to project
    if media.project_id != clean_project_id:
        logger.warning(
            f"Vision analysis rejected: Media '{clean_media_id}' belongs to '{media.project_id}', not '{clean_project_id}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MEDIA_PROJECT_MISMATCH",
                "message": f"Media file '{clean_media_id}' does not belong to project '{clean_project_id}'.",
            },
        )

    # 4. Verify media is a supported video
    if media.file_type != "source_video":
        logger.warning(f"Vision analysis rejected: Media '{clean_media_id}' is '{media.file_type}', not 'source_video'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_MEDIA_TYPE",
                "message": f"Media file is not a source video (type: '{media.file_type}'). Only source videos can be analyzed for vision features.",
            },
        )

    # 5. Verify physical source video exists on disk
    base_storage = get_base_storage_dir()
    video_file_path = base_storage / media.file_path
    if not video_file_path.exists() or not video_file_path.is_file():
        logger.error(f"Source video physical file missing on disk: {video_file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "VIDEO_FILE_NOT_FOUND",
                "message": "Physical video file is missing from storage.",
            },
        )

    # 6. Retrieve Phase 7 keyframe records if available
    video_analysis = (
        db.query(VideoAnalysis)
        .options(selectinload(VideoAnalysis.scenes).selectinload(VideoScene.keyframes).selectinload(SceneKeyframe.media_file))
        .filter(VideoAnalysis.source_media_id == clean_media_id)
        .first()
    )
    keyframe_records = []
    if video_analysis:
        for s in video_analysis.scenes:
            for kf in s.keyframes:
                keyframe_records.append(kf)

    # 7. Idempotency: Clean up previous vision analysis and orphaned face reference files for this source media
    existing_analyses = (
        db.query(VisionAnalysis)
        .options(
            selectinload(VisionAnalysis.face_references),
            selectinload(VisionAnalysis.subjects),
        )
        .filter(VisionAnalysis.source_media_id == clean_media_id)
        .all()
    )
    for old_analysis in existing_analyses:
        for old_ref in old_analysis.face_references:
            old_media_record = db.query(MediaFile).filter(MediaFile.id == old_ref.media_file_id).first()
            if old_media_record:
                old_path = base_storage / old_media_record.file_path
                if old_path.exists():
                    try:
                        old_path.unlink()
                    except Exception:
                        pass
                db.delete(old_media_record)
        db.delete(old_analysis)
    db.commit()

    # 8. Run Vision Analysis Pipeline
    result = run_vision_analysis_pipeline(
        project_id=clean_project_id,
        video_path=video_file_path,
        keyframe_records=keyframe_records,
    )

    # 9. Persist Records in Database
    analysis_id = generate_uuid()
    primary_subject_db_id = None

    subject_records: List[DetectedSubject] = []
    face_records: List[FaceDetection] = []
    pose_records: List[PoseDetection] = []
    landmark_records: List[PoseLandmark] = []
    face_ref_media_records: List[MediaFile] = []
    face_ref_records: List[FaceReference] = []

    for s_res in result.subjects:
        subj_id = generate_uuid()
        if s_res.is_primary:
            primary_subject_db_id = subj_id

        subj_record = DetectedSubject(
            id=subj_id,
            analysis_id=analysis_id,
            sequence=s_res.sequence,
            is_primary=s_res.is_primary,
            confidence=s_res.confidence,
        )
        subject_records.append(subj_record)

        for f_res in s_res.face_detections:
            landmarks_json = json.dumps([
                {"name": lm.name, "x": lm.x, "y": lm.y}
                for lm in f_res.landmarks
            ]) if f_res.landmarks else None

            face_records.append(
                FaceDetection(
                    id=generate_uuid(),
                    subject_id=subj_id,
                    timestamp=f_res.timestamp,
                    frame_reference=f_res.frame_reference,
                    x=f_res.x,
                    y=f_res.y,
                    width=f_res.width,
                    height=f_res.height,
                    confidence=f_res.confidence,
                    landmarks_data=landmarks_json,
                )
            )

        for p_res in s_res.pose_detections:
            pose_id = generate_uuid()
            pose_record = PoseDetection(
                id=pose_id,
                subject_id=subj_id,
                timestamp=p_res.timestamp,
                frame_reference=p_res.frame_reference,
                confidence=p_res.confidence,
            )
            pose_records.append(pose_record)

            for lm in p_res.landmarks:
                landmark_records.append(
                    PoseLandmark(
                        id=generate_uuid(),
                        pose_detection_id=pose_id,
                        landmark_index=lm.landmark_index,
                        landmark_name=lm.landmark_name,
                        x=lm.x,
                        y=lm.y,
                        z=lm.z,
                        visibility=lm.visibility,
                    )
                )

    # Save Face Reference Media & Records
    for ref_res in result.face_references:
        ref_media = MediaFile(
            id=ref_res.media_file_id,
            project_id=clean_project_id,
            file_type="face_reference",
            original_filename=f"face_ref_{ref_res.timestamp:.2f}s.jpg",
            stored_filename=ref_res.stored_filename,
            file_path=ref_res.relative_path,
            mime_type="image/jpeg",
            file_size=ref_res.file_size,
            sha256_hash=ref_res.sha256_hash,
        )
        face_ref_media_records.append(ref_media)

        ref_record = FaceReference(
            id=generate_uuid(),
            analysis_id=analysis_id,
            subject_id=primary_subject_db_id or (subject_records[0].id if subject_records else subj_id),
            media_file_id=ref_res.media_file_id,
            timestamp=ref_res.timestamp,
            quality_score=ref_res.quality_score,
        )
        face_ref_records.append(ref_record)

    analysis_record = VisionAnalysis(
        id=analysis_id,
        project_id=clean_project_id,
        source_media_id=clean_media_id,
        primary_subject_id=primary_subject_db_id,
        faces_detected_count=result.faces_detected_count,
        pose_frames_count=result.pose_frames_count,
    )

    try:
        db.add(analysis_record)
        db.add_all(subject_records)
        db.add_all(face_records)
        db.add_all(pose_records)
        db.add_all(landmark_records)
        db.add_all(face_ref_media_records)
        db.add_all(face_ref_records)
        db.commit()
        db.refresh(analysis_record)
        logger.info(
            f"Vision analysis saved: ID='{analysis_record.id}', Project='{clean_project_id}', "
            f"Subjects={len(subject_records)}, Faces={len(face_records)}, Poses={len(pose_records)}, "
            f"FaceRefs={len(face_ref_records)}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to persist vision analysis in database: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "DATABASE_PERSISTENCE_FAILED",
                "message": "Failed to persist vision analysis records to the database.",
            },
        )

    # Re-fetch with eager loaded relationships
    eager_analysis = (
        db.query(VisionAnalysis)
        .options(
            selectinload(VisionAnalysis.subjects).selectinload(DetectedSubject.face_detections),
            selectinload(VisionAnalysis.subjects).selectinload(DetectedSubject.pose_detections).selectinload(PoseDetection.landmarks),
            selectinload(VisionAnalysis.face_references),
        )
        .filter(VisionAnalysis.id == analysis_id)
        .first()
    )

    return VisionAnalysisResponse(
        success=True,
        analysis=VisionAnalysisDetail.model_validate(eager_analysis or analysis_record),
    )


@router.get(
    "/{project_id}/media/{media_id}/file",
    summary="Get media file content",
    description="Streams or returns the binary content of a project media file.",
)
async def get_media_file(
    project_id: str,
    media_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the binary content of a stored media file (source video, face reference, audio, or keyframe).
    """
    clean_project_id = project_id.strip()
    clean_media_id = media_id.strip()

    # Verify project ownership
    project = get_owned_project(clean_project_id, current_user, db)

    media = db.query(MediaFile).filter(MediaFile.id == clean_media_id, MediaFile.project_id == project.id).first()
    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEDIA_NOT_FOUND", "message": "Media file not found."},
        )

    base_storage = get_base_storage_dir()
    file_path = base_storage / media.file_path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "FILE_NOT_FOUND", "message": "File not found on disk."},
        )

    return FileResponse(
        path=file_path,
        media_type=media.mime_type or "application/octet-stream",
        filename=media.original_filename,
    )


@router.post(
    "/{project_id}/comic-generation",
    response_model=ComicGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate 3D Comic Style Frames",
    description="Transforms video scene keyframes into 3D comic-style visual frames using configured image generation provider.",
)
async def generate_comic_frames(
    project_id: str,
    payload: ComicGenerationRequest = ComicGenerationRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComicGenerationResponse:
    """
    Generates 3D comic visual frames for a project session.
    Phase 9: 3D Comic Style Generation
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    generation = run_comic_generation_pipeline(
        db=db,
        project_id=clean_project_id,
        scene_id=payload.scene_id,
        scene_ids=payload.scene_ids,
        style_preset=payload.style_preset or "3d-comic",
        prompt_override=payload.prompt_override,
    )

    return ComicGenerationResponse(
        success=True,
        generation=ComicGenerationDetail.model_validate(generation),
    )


@router.post(
    "/{project_id}/consistency/profile",
    response_model=ConsistencyProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get or Create Character Consistency Profile",
    description="Builds or retrieves a project-local character consistency profile for the primary subject based on Phase 8 vision analysis.",
)
async def get_or_create_consistency_profile(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsistencyProfileResponse:
    """
    Retrieves or constructs a project-local character consistency profile.
    Phase 10: Identity + Temporal Consistency Engine
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    profile = CharacterConsistencyService.get_or_create_profile(clean_project_id, db)

    return ConsistencyProfileResponse(
        success=True,
        profile=CharacterConsistencyProfileDetail.model_validate(profile),
    )


@router.post(
    "/{project_id}/consistency/generate",
    response_model=ConsistencyGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Identity-Consistent 3D Comic Frames",
    description="Generates identity-consistent and temporally coherent 3D comic frames across scenes using canonical references and style locking.",
)
async def generate_consistent_comic_frames(
    project_id: str,
    payload: ConsistencyGenerationRequest = ConsistencyGenerationRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsistencyGenerationResponse:
    """
    Generates identity-consistent 3D comic frames for a scene or batch of scenes.
    Phase 10: Identity + Temporal Consistency Engine
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    generation = run_consistency_generation_pipeline(
        db=db,
        project_id=clean_project_id,
        scene_id=payload.scene_id,
        scene_ids=payload.scene_ids,
        style_preset=payload.style_preset or "3d-comic",
        prompt_override=payload.prompt_override,
        force_regenerate=payload.force_regenerate or False,
    )

    return ConsistencyGenerationResponse(
        success=True,
        generation=ConsistencyGenerationDetail.model_validate(generation),
    )


@router.post(
    "/{project_id}/segmentation",
    response_model=SegmentationResponse,
    status_code=status.HTTP_200_OK,
    summary="Segment Foreground & Generate Layered Background Scene",
    description="Isolates primary subject character, generates soft alpha mask, inpaint-reconstructs background, applies adaptation mode, and outputs composite preview.",
)
async def segment_foreground_and_background(
    project_id: str,
    payload: SegmentationRequest = SegmentationRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SegmentationResponse:
    """
    Executes foreground character isolation and dynamic background layer adaptation.
    Phase 11: Foreground Segmentation + Dynamic Background
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    results = run_segmentation_pipeline(
        db=db,
        project_id=clean_project_id,
        consistent_frame_id=payload.consistent_frame_id,
        consistent_frame_ids=payload.consistent_frame_ids,
        scene_id=payload.scene_id,
        scene_ids=payload.scene_ids,
        background_mode=payload.background_mode or "ORIGINAL",
        refinement_params=payload.refinement_params,
        force_regenerate=payload.force_regenerate or False,
    )

    summaries = [SegmentationResultDetail.model_validate(r) for r in results]
    return SegmentationResponse(
        success=True,
        results=summaries,
        count=len(summaries),
    )


@router.post(
    "/{project_id}/lyrics/sync",
    response_model=LyricSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Synchronize Transcript into Editable Kinetic Lyric Segments",
    description="Converts timestamped Phase 6 transcript segments into kinetic lyric segments with default styles and animation presets.",
)
async def sync_project_lyrics(
    project_id: str,
    payload: LyricSyncRequest = LyricSyncRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LyricSyncResponse:
    """
    Synchronizes transcript segments to lyric segments.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    segments, styles, animations = sync_transcript_to_lyrics(
        db=db,
        project_id=clean_project_id,
        force_recreate=payload.force_recreate or False,
        default_style_name=payload.default_style_name,
        default_animation_name=payload.default_animation_name,
    )

    return LyricSyncResponse(
        success=True,
        segments=[LyricSegmentSummary.model_validate(s) for s in segments],
        styles=[LyricStyleSummary.model_validate(st) for st in styles],
        animations=[LyricAnimationSummary.model_validate(a) for a in animations],
        count=len(segments),
    )


@router.get(
    "/{project_id}/lyrics",
    response_model=LyricListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Kinetic Lyrics Configuration & Segments",
    description="Retrieves all lyric segments, styles, animations, and preview frames for a project.",
)
async def get_project_lyrics(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LyricListResponse:
    """
    Retrieves project lyrics configuration and segments.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    # Ensure default styles and animations exist
    styles = get_or_create_default_styles(db, clean_project_id)
    animations = get_or_create_default_animations(db, clean_project_id)

    segments = (
        db.query(LyricSegment)
        .filter(LyricSegment.project_id == clean_project_id)
        .order_by(LyricSegment.sequence)
        .all()
    )
    if not segments:
        synced_segs, styles, animations = sync_transcript_to_lyrics(db, clean_project_id)
        segments = synced_segs

    previews = (
        db.query(LyricPreview)
        .filter(LyricPreview.project_id == clean_project_id)
        .order_by(LyricPreview.created_at.desc())
        .all()
    )

    return LyricListResponse(
        success=True,
        segments=[LyricSegmentSummary.model_validate(s) for s in segments],
        styles=[LyricStyleSummary.model_validate(st) for st in styles],
        animations=[LyricAnimationSummary.model_validate(a) for a in animations],
        previews=[LyricPreviewDetail.model_validate(p) for p in previews],
    )


@router.patch(
    "/{project_id}/lyrics/segments/{segment_id}",
    response_model=LyricSegmentSummary,
    status_code=status.HTTP_200_OK,
    summary="Update Lyric Segment Parameters",
    description="Updates text, timing, styling, animation, normalized positioning (x,y), scale, or opacity for a lyric segment.",
)
async def update_lyric_segment(
    project_id: str,
    segment_id: str,
    payload: LyricSegmentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LyricSegmentSummary:
    """
    Updates a specific lyric segment.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    clean_project_id = project_id.strip()
    clean_segment_id = segment_id.strip()

    project = get_owned_project(clean_project_id, current_user, db)
    segment = (
        db.query(LyricSegment)
        .filter(LyricSegment.id == clean_segment_id, LyricSegment.project_id == clean_project_id)
        .first()
    )
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LYRIC_SEGMENT_NOT_FOUND", "message": f"Lyric segment '{clean_segment_id}' not found."},
        )

    if payload.text is not None:
        segment.text = payload.text.strip()
    if payload.style_id is not None:
        segment.style_id = payload.style_id
    if payload.animation_id is not None:
        segment.animation_id = payload.animation_id
    if payload.position_x is not None:
        segment.position_x = max(0.0, min(1.0, payload.position_x))
    if payload.position_y is not None:
        segment.position_y = max(0.0, min(1.0, payload.position_y))
    if payload.scale is not None:
        segment.scale = max(0.1, min(5.0, payload.scale))
    if payload.rotation is not None:
        segment.rotation = payload.rotation
    if payload.opacity is not None:
        segment.opacity = max(0.0, min(1.0, payload.opacity))
    if payload.z_layer is not None:
        segment.z_layer = payload.z_layer
    if payload.enabled is not None:
        segment.enabled = payload.enabled
    if payload.start_time is not None:
        segment.start_time = payload.start_time
    if payload.end_time is not None:
        segment.end_time = payload.end_time

    db.commit()
    db.refresh(segment)

    return LyricSegmentSummary.model_validate(segment)


@router.post(
    "/{project_id}/lyrics/preview",
    response_model=LyricPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Render Text-Behind-Character Preview Frame",
    description="Composites kinetic text behind the segmented foreground character for a timestamp or scene, outputting a preview image asset.",
)
async def preview_lyric_composite(
    project_id: str,
    payload: LyricPreviewRequest = LyricPreviewRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LyricPreviewResponse:
    """
    Renders text-behind-character composite preview.
    Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    try:
        preview_record = generate_lyric_preview(
            db=db,
            project_id=clean_project_id,
            scene_id=payload.scene_id,
            segmentation_id=payload.segmentation_id,
            lyric_segment_id=payload.lyric_segment_id,
            timestamp=payload.timestamp,
            text_override=payload.text_override,
            position_x=payload.position_x,
            position_y=payload.position_y,
            scale=payload.scale,
            opacity=payload.opacity,
            style_id=payload.style_id,
            animation_id=payload.animation_id,
        )
    except ValueError as e:
        logger.warning(f"Lyric preview generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "LYRIC_PREVIEW_ERROR", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"Unexpected error rendering lyric preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "LYRIC_RENDER_FAILED", "message": "Failed to render lyric preview frame."},
        )

    return LyricPreviewResponse(
        success=True,
        preview=LyricPreviewDetail.model_validate(preview_record),
    )


# ===================================================================
# PHASE 13: FINAL VIDEO COMPOSITING + 9:16 REEL RENDERING ENDPOINTS
# ===================================================================


@router.post(
    "/{project_id}/render",
    response_model=RenderJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Render Final 9:16 3D Comic Reel MP4",
    description="Composites all scene visuals, foreground character matting, background styling, kinetic typography, and synchronized AAC audio into a vertical 1080x1920 MP4 Reel.",
)
async def render_project_reel(
    project_id: str,
    payload: RenderJobRequest = RenderJobRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RenderJobResponse:
    """
    Renders the final vertical 9:16 3D Comic Reel MP4.
    Phase 13: Final Video Compositing + 9:16 Reel Rendering
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    source_video = (
        db.query(MediaFile)
        .filter(MediaFile.project_id == clean_project_id, MediaFile.file_type == "source_video")
        .first()
    )
    if not source_video:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SOURCE_VIDEO_MISSING", "message": "Source video must be ingested before rendering final reel."},
        )

    # In-flight check: Prevent duplicate concurrent render jobs for same project
    existing_in_flight = (
        db.query(RenderJob)
        .filter(
            RenderJob.project_id == clean_project_id,
            RenderJob.status.in_(["processing", "queued"]),
        )
        .order_by(RenderJob.created_at.desc())
        .first()
    )
    if existing_in_flight:
        logger.info(f"Render job {existing_in_flight.id} already in-flight for project {clean_project_id}.")
        return RenderJobResponse(
            success=True,
            job=RenderJobSummary.model_validate(existing_in_flight),
        )

    # Idempotency: Check if completed render already exists
    if not payload.force_rerender:
        existing_completed = (
            db.query(RenderJob)
            .filter(
                RenderJob.project_id == clean_project_id,
                RenderJob.status == "completed",
                RenderJob.output_media_file_id.isnot(None),
            )
            .order_by(RenderJob.created_at.desc())
            .first()
        )
        if existing_completed:
            out_mf = db.query(MediaFile).filter(MediaFile.id == existing_completed.output_media_file_id).first()
            if out_mf and Path(out_mf.file_path).is_file():
                return RenderJobResponse(
                    success=True,
                    job=RenderJobSummary.model_validate(existing_completed),
                )

    # Create new RenderJob
    render_job = RenderJob(
        project_id=clean_project_id,
        source_media_id=source_video.id,
        status="queued",
        width=payload.output_width,
        height=payload.output_height,
        fps=payload.fps,
        video_codec=payload.video_codec,
        audio_codec=payload.audio_codec,
        render_config=payload.model_dump(),
        stage_message="Queued for final 9:16 Reel render...",
    )
    db.add(render_job)
    db.commit()
    db.refresh(render_job)

    try:
        completed_job = run_final_reel_render_sync(
            db=db,
            project_id=clean_project_id,
            job_id=render_job.id,
            output_width=payload.output_width,
            output_height=payload.output_height,
            fps=payload.fps,
            video_codec=payload.video_codec,
            audio_codec=payload.audio_codec,
            include_audio=payload.include_audio,
            include_lyrics=payload.include_lyrics,
        )
    except ValueError as e:
        logger.warning(f"Render job error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "RENDER_VALIDATION_ERROR", "message": str(e)},
        )
    except Exception as e:
        logger.error(f"Unexpected error rendering final reel: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "RENDER_EXECUTION_FAILED", "message": "Failed to render final reel video."},
        )

    return RenderJobResponse(
        success=True,
        job=RenderJobSummary.model_validate(completed_job),
    )


@router.get(
    "/{project_id}/render",
    response_model=RenderJobListResponse,
    status_code=status.HTTP_200_OK,
    summary="List project render jobs",
    description="Lists all final render jobs for a project ordered by creation time.",
)
async def list_project_render_jobs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RenderJobListResponse:
    """
    Retrieves history and latest status of render jobs for a project.
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    jobs = (
        db.query(RenderJob)
        .filter(RenderJob.project_id == clean_project_id)
        .order_by(RenderJob.created_at.desc())
        .all()
    )

    latest = jobs[0] if jobs else None

    return RenderJobListResponse(
        success=True,
        jobs=[RenderJobSummary.model_validate(j) for j in jobs],
        count=len(jobs),
        latest_render=RenderJobSummary.model_validate(latest) if latest else None,
    )


@router.get(
    "/{project_id}/render/{render_id}",
    response_model=RenderJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get render job detail",
    description="Retrieves status, progress, duration, and output media reference for a specific render job.",
)
async def get_render_job(
    project_id: str,
    render_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RenderJobResponse:
    """
    Retrieves status of a specific render job.
    """
    clean_project_id = project_id.strip()
    clean_render_id = render_id.strip()

    project = get_owned_project(clean_project_id, current_user, db)

    job = (
        db.query(RenderJob)
        .filter(RenderJob.id == clean_render_id, RenderJob.project_id == project.id)
        .first()
    )
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RENDER_JOB_NOT_FOUND", "message": f"Render job '{clean_render_id}' not found."},
        )

    return RenderJobResponse(
        success=True,
        job=RenderJobSummary.model_validate(job),
    )


@router.post(
    "/{project_id}/render/{render_id}/cancel",
    response_model=RenderJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel active render job",
    description="Cancels an active or queued render job and cleans up temporary resources.",
)
async def cancel_project_render_job(
    project_id: str,
    render_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RenderJobResponse:
    """
    Cancels an active render job.
    """
    clean_project_id = project_id.strip()
    clean_render_id = render_id.strip()

    project = get_owned_project(clean_project_id, current_user, db)
    job = db.query(RenderJob).filter(RenderJob.id == clean_render_id, RenderJob.project_id == project.id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RENDER_JOB_NOT_FOUND", "message": f"Render job '{clean_render_id}' not found."},
        )

    cancelled_job = cancel_render_job(db, clean_project_id, clean_render_id)
    return RenderJobResponse(
        success=True,
        job=RenderJobSummary.model_validate(cancelled_job),
    )


# ===================================================================
# PHASE 14: PRODUCTION HARDENING & STORAGE MAINTENANCE ENDPOINTS
# ===================================================================


@router.get(
    "/{project_id}/storage-audit",
    response_model=StorageAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Audit project media storage integrity",
    description="Performs non-destructive diagnostic audit validating database MediaFile records against disk storage.",
)
async def get_project_storage_audit(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StorageAuditResponse:
    """
    Diagnostic storage audit endpoint for observability and health validation.
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    audit_result = audit_project_storage(db, clean_project_id)
    return StorageAuditResponse(
        success=True,
        project_id=clean_project_id,
        is_healthy=audit_result["is_healthy"],
        summary=audit_result["summary"],
        missing_files=audit_result["missing_files"],
        zero_byte_files=audit_result["zero_byte_files"],
        checksum_mismatches=audit_result["checksum_mismatches"],
        unreferenced_files=audit_result["unreferenced_files"],
        stale_temp_dirs=audit_result["stale_temp_dirs"],
    )


@router.post(
    "/{project_id}/storage-cleanup",
    response_model=StorageCleanupResponse,
    status_code=status.HTTP_200_OK,
    summary="Safely clean up project storage",
    description="Safely cleans abandoned temporary directories or unreferenced orphaned files with default dry_run=True protection.",
)
async def post_project_storage_cleanup(
    project_id: str,
    payload: StorageCleanupRequest = StorageCleanupRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StorageCleanupResponse:
    """
    Storage maintenance endpoint with dry-run safety by default.
    """
    clean_project_id = project_id.strip()
    project = get_owned_project(clean_project_id, current_user, db)

    cleanup_result = cleanup_project_storage(
        db=db,
        project_id=clean_project_id,
        dry_run=payload.dry_run,
        clean_stale_temp=payload.clean_stale_temp,
        clean_unreferenced=payload.clean_unreferenced,
    )

    return StorageCleanupResponse(
        success=True,
        project_id=clean_project_id,
        dry_run=cleanup_result["dry_run"],
        actions_taken=cleanup_result["actions_taken"],
        audit_after=cleanup_result["audit_after"],
    )




