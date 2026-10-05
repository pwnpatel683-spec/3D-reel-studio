"""
3D Reel Studio — 3D Comic Style Generation Service
Phase 9: 3D Comic Style Generation
"""

import base64
import hashlib
import io
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import HTTPException, status
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models.project import (
    ComicFrame,
    ComicGeneration,
    DetectedSubject,
    FaceReference,
    MediaFile,
    Project,
    SceneKeyframe,
    VideoAnalysis,
    VideoScene,
    VisionAnalysis,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir


class ComicGenerationServiceError(Exception):
    """Custom exception raised during 3D comic generation processing."""
    def __init__(self, message: str, error_code: str = "COMIC_GENERATION_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


# -----------------------------------------------------------------------------
# 1. Prompt Construction Engine
# -----------------------------------------------------------------------------

STYLE_PRESETS: Dict[str, Dict[str, str]] = {
    "3d-comic": {
        "name": "3D Comic",
        "description": "hyper-detailed 3D comic illustration style, cinematic dynamic lighting, crisp ink contours, vibrant cell-shading, rich halftone textures, stylized Marvel/DC cinematic graphic novel aesthetic, volumetric depth, photorealistic material textures",
        "color_palette": "vibrant contrast with saturated tones and dark ink shadows",
    },
    "cyber-hero": {
        "name": "Cyber Hero",
        "description": "futuristic cyberpunk comic style, neon cyan and magenta rim lighting, high-tech stylized materials, bold graphic novel linework, cinematic atmospheric haze, 3D character render",
        "color_palette": "electric cyan, hot neon pink, deep obsidian blacks",
    },
    "manga-noir": {
        "name": "Manga Noir",
        "description": "high-contrast dramatic 3D manga noir style, intense chiaroscuro ink crosshatching, cinematic perspective, sharp stylized character silhouettes, expressive lighting",
        "color_palette": "monochromatic black and white with subtle glowing amber highlights",
    },
}


def build_comic_generation_prompt(
    style_preset: str = "3d-comic",
    primary_subject_info: Optional[Dict[str, Any]] = None,
    face_reference_present: bool = False,
    pose_summary: Optional[str] = None,
    scene_sequence: int = 1,
    aspect_ratio: str = "9:16",
    prompt_override: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Constructs a detailed, controlled 3D comic style generation prompt.
    Preserves original scene framing, character pose, and recognizable features
    without claiming 100% identity preservation.
    Returns (prompt_text, prompt_version).
    """
    version_tag = f"v1-{style_preset.lower().strip()}"

    if prompt_override and prompt_override.strip():
        custom_prompt = prompt_override.strip()
        final_prompt = (
            f"Cinematic 3D comic illustration: {custom_prompt}. "
            f"Vertical 9:16 vertical reel composition, hyper-detailed stylized character render, "
            f"clean ink contours, dynamic lighting, professional graphic novel artwork, "
            f"avoid distorted anatomy, duplicate limbs, random text, watermarks."
        )
        return final_prompt, version_tag

    preset = STYLE_PRESETS.get(style_preset.lower(), STYLE_PRESETS["3d-comic"])
    style_desc = preset["description"]
    palette_desc = preset["color_palette"]

    subject_desc = "main character centered in the frame"
    if primary_subject_info:
        if primary_subject_info.get("is_primary"):
            subject_desc = "prominent hero character positioned according to the original scene composition"

    pose_desc = "maintaining a natural, dynamic body posture consistent with the video shot"
    if pose_summary:
        pose_desc = f"character in {pose_summary}"

    identity_guideline = (
        "with recognizable facial characteristics guided by the reference frame, "
        "expressive stylized eyes, clean jawline, stylized hair, and detailed clothing"
        if face_reference_present
        else "with expressive facial features, stylized hair, and detailed clothing"
    )

    prompt = (
        f"A masterwork cinematic 3D comic frame in {style_desc}. "
        f"Scene framing: {subject_desc}, {pose_desc}, {identity_guideline}. "
        f"Color grading: {palette_desc}. "
        f"Composition: vertical 9:16 social reel format, dramatic camera angle, sharp focus, "
        f"cinematic rim lighting, high-contrast ink crosshatching, volumetric depth. "
        f"Avoid: distorted anatomy, extra fingers, duplicate people, malformed faces, blurry elements, text, captions, watermarks."
    )

    return prompt, version_tag


# -----------------------------------------------------------------------------
# 2. Provider Abstraction
# -----------------------------------------------------------------------------

class ComicGenerationProvider(ABC):
    """
    Abstract provider interface for 3D comic image generation.
    Decouples specific model implementations from application logic.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns the canonical provider identifier (e.g. 'openai', 'mock')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Returns the model name used by this provider (e.g. 'dall-e-3')."""
        pass

    @abstractmethod
    def generate_comic_frame(
        self,
        prompt: str,
        keyframe_path: Optional[Path] = None,
        reference_image_path: Optional[Path] = None,
        width: int = 1024,
        height: int = 1792,
        **kwargs: Any,
    ) -> Tuple[bytes, int, int]:
        """
        Generates a 3D comic-style frame from prompt and optional visual references.
        Returns: (image_bytes, width, height).
        """
        pass


# -----------------------------------------------------------------------------
# 3. OpenAI Image Generation Provider (DALL-E 3)
# -----------------------------------------------------------------------------

class OpenAIComicProvider(ComicGenerationProvider):
    """
    Generates 3D comic frames using the official OpenAI Images API (DALL-E 3).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        openai_client: Optional[Any] = None,
    ):
        self._api_key = (api_key or settings.COMIC_GENERATION_API_KEY or settings.OPENAI_API_KEY or "").strip()
        self._model = (model or settings.COMIC_GENERATION_MODEL or "dall-e-3").strip()
        self._client = openai_client

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            logger.error("3D Comic generation requested but OPENAI_API_KEY is not configured.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_COMIC_API_KEY",
                    "message": "OpenAI API key is not configured on the server. Please set COMIC_GENERATION_API_KEY or OPENAI_API_KEY.",
                },
            )
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
            return self._client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "OPENAI_INIT_ERROR",
                    "message": "Failed to initialize OpenAI client.",
                },
            )

    def generate_comic_frame(
        self,
        prompt: str,
        keyframe_path: Optional[Path] = None,
        reference_image_path: Optional[Path] = None,
        width: int = 1024,
        height: int = 1792,
        **kwargs: Any,
    ) -> Tuple[bytes, int, int]:
        client = self._get_client()

        # DALL-E 3 supports vertical 1024x1792 natively
        size_str = "1024x1792" if (width <= 1024 and height >= 1700) else "1024x1024"
        out_w, out_h = (1024, 1792) if size_str == "1024x1792" else (1024, 1024)

        logger.info(f"[OpenAIComicProvider] Calling Images API model='{self._model}', size='{size_str}'")

        try:
            from openai import (
                APIConnectionError,
                APIError,
                APIStatusError,
                AuthenticationError,
                RateLimitError,
            )

            response = client.images.generate(
                model=self._model,
                prompt=prompt,
                size=size_str,
                quality="standard",
                response_format="b64_json",
                n=1,
            )
        except AuthenticationError as auth_err:
            logger.error(f"OpenAI authentication failed: {auth_err}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "OPENAI_AUTH_ERROR",
                    "message": "OpenAI API authentication failed. Please verify your API key.",
                },
            )
        except RateLimitError as rate_err:
            logger.warning(f"OpenAI rate limit hit: {rate_err}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "OPENAI_RATE_LIMIT",
                    "message": "OpenAI API rate limit or quota exceeded. Please try again later.",
                },
            )
        except APIConnectionError as conn_err:
            logger.error(f"OpenAI connection error: {conn_err}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "OPENAI_CONNECTION_ERROR",
                    "message": "Failed to connect to OpenAI generation services. Check network connectivity.",
                },
            )
        except (APIStatusError, APIError) as api_err:
            logger.error(f"OpenAI API status error: {api_err}")
            code = getattr(api_err, "status_code", 502)
            if not isinstance(code, int) or code < 400:
                code = 502
            raise HTTPException(
                status_code=code,
                detail={
                    "code": "OPENAI_API_ERROR",
                    "message": "OpenAI generation service encountered an error.",
                },
            )
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise exc
            logger.error(f"Unexpected error during comic generation: {exc}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "COMIC_GENERATION_FAILED",
                    "message": "3D comic generation encountered an unexpected internal error.",
                },
            )

        if not response or not getattr(response, "data", None):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "EMPTY_GENERATION_RESPONSE",
                    "message": "OpenAI returned an empty generation response.",
                },
            )

        item = response.data[0]
        b64_data = getattr(item, "b64_json", None)

        if b64_data:
            image_bytes = base64.b64decode(b64_data)
        elif getattr(item, "url", None):
            # Fallback for URL responses
            import urllib.request
            with urllib.request.urlopen(item.url, timeout=30) as url_resp:
                image_bytes = url_resp.read()
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "INVALID_IMAGE_PAYLOAD",
                    "message": "No valid image data received from generation provider.",
                },
            )

        return image_bytes, out_w, out_h


# -----------------------------------------------------------------------------
# 4. Mock / Offline Provider for Deterministic Testing & Local Fallback
# -----------------------------------------------------------------------------

class MockComicProvider(ComicGenerationProvider):
    """
    Synthesizes a rich, high-contrast 3D comic illustration frame locally
    using Pillow (PIL) for offline environments and automated test suites.
    """

    def __init__(self, model: str = "mock-3d-comic-v1"):
        self._model = model

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    def generate_comic_frame(
        self,
        prompt: str,
        keyframe_path: Optional[Path] = None,
        reference_image_path: Optional[Path] = None,
        width: int = 1024,
        height: int = 1792,
        **kwargs: Any,
    ) -> Tuple[bytes, int, int]:
        target_w = width or 1024
        target_h = height or 1792

        # Create 9:16 vertical canvas
        img = Image.new("RGB", (target_w, target_h), color=(11, 12, 16))
        draw = ImageDraw.Draw(img)

        # 1. If keyframe exists, stylize and composite as background
        if keyframe_path and keyframe_path.exists():
            try:
                with Image.open(keyframe_path) as kf_img:
                    kf_rgb = kf_img.convert("RGB")
                    # Scale to fit 9:16 vertical canvas while preserving center
                    kf_fitted = ImageOps.fit(kf_rgb, (target_w, target_h), method=Image.Resampling.LANCZOS)
                    # Apply high-contrast comic stylization filter
                    stylized = kf_fitted.filter(ImageFilter.EDGE_ENHANCE_MORE)
                    stylized = ImageOps.posterize(stylized, 4)
                    img.paste(stylized, (0, 0))
            except Exception as e:
                logger.warning(f"MockComicProvider: could not load keyframe '{keyframe_path}': {e}")

        # 2. Draw 3D Comic Vignette & Halftone Graphic Frame
        draw = ImageDraw.Draw(img, "RGBA")
        
        # Cyber Cyan & Neon Red Comic Border Frame
        border_pad = 24
        draw.rectangle(
            [(border_pad, border_pad), (target_w - border_pad, target_h - border_pad)],
            outline=(0, 255, 245, 220),
            width=6,
        )
        draw.rectangle(
            [(border_pad + 8, border_pad + 8), (target_w - border_pad - 8, target_h - border_pad - 8)],
            outline=(255, 46, 99, 180),
            width=2,
        )

        # Comic Halftone / Dot Grid Header Accent
        for x_dot in range(border_pad + 20, target_w - border_pad - 20, 24):
            for y_dot in range(border_pad + 20, border_pad + 80, 16):
                draw.ellipse([(x_dot, y_dot), (x_dot + 4, y_dot + 4)], fill=(0, 255, 245, 90))

        # Bottom Comic Caption Shield
        caption_box = [(border_pad + 16, target_h - 140), (target_w - border_pad - 16, target_h - border_pad - 16)]
        draw.rectangle(caption_box, fill=(11, 12, 16, 230), outline=(0, 255, 245, 180), width=2)
        
        # Stylized Text Tag
        draw.text(
            (border_pad + 32, target_h - 110),
            "⚡ 3D COMIC STYLE REEL FRAME",
            fill=(0, 255, 245, 255),
        )
        draw.text(
            (border_pad + 32, target_h - 75),
            "9:16 VERTICAL • AI STYLIZED VISUAL SCENE",
            fill=(200, 205, 220, 220),
        )

        # Output bytes
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), target_w, target_h


# -----------------------------------------------------------------------------
# 5. Provider Factory
# -----------------------------------------------------------------------------

def get_comic_generation_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    openai_client: Optional[Any] = None,
) -> ComicGenerationProvider:
    """
    Returns an instantiated ComicGenerationProvider based on configuration or override.
    """
    target_provider = (provider_name or settings.COMIC_GENERATION_PROVIDER or "openai").strip().lower()

    if target_provider == "openai":
        return OpenAIComicProvider(api_key=api_key, model=model, openai_client=openai_client)
    elif target_provider == "mock":
        return MockComicProvider(model=model or "mock-3d-comic-v1")
    else:
        logger.error(f"Unsupported comic generation provider requested: '{target_provider}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_PROVIDER",
                "message": f"Unsupported comic generation provider '{target_provider}'. Supported: 'openai', 'mock'.",
            },
        )


# -----------------------------------------------------------------------------
# 6. Comic Generation Pipeline Orchestration
# -----------------------------------------------------------------------------

def run_comic_generation_pipeline(
    db: Session,
    project_id: str,
    scene_id: Optional[str] = None,
    scene_ids: Optional[List[str]] = None,
    style_preset: str = "3d-comic",
    prompt_override: Optional[str] = None,
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    openai_client: Optional[Any] = None,
) -> ComicGeneration:
    """
    Executes the 3D Comic visual generation pipeline for selected scene keyframes.
    Persists output images to project storage and records in the database.
    """
    # 1. Validate Project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        logger.error(f"Project '{project_id}' not found for comic generation.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "PROJECT_NOT_FOUND",
                "message": f"Project '{project_id}' was not found.",
            },
        )

    # 2. Validate Phase 7 Video Analysis
    video_analysis = (
        db.query(VideoAnalysis)
        .filter(VideoAnalysis.project_id == project_id)
        .order_by(VideoAnalysis.created_at.desc())
        .first()
    )
    if not video_analysis:
        logger.error(f"No Phase 7 video analysis found for project '{project_id}'.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MISSING_SCENE_ANALYSIS",
                "message": "Video scene analysis (Phase 7) is required before 3D comic generation. Please analyze the video first.",
            },
        )

    # 3. Validate Phase 8 Vision Analysis (optional reference context)
    vision_analysis = (
        db.query(VisionAnalysis)
        .filter(VisionAnalysis.project_id == project_id)
        .order_by(VisionAnalysis.created_at.desc())
        .first()
    )

    # Primary subject & face reference lookup
    primary_subject_info = None
    face_ref_path: Optional[Path] = None
    face_ref_present = False

    if vision_analysis:
        primary_subject = (
            db.query(DetectedSubject)
            .filter(
                DetectedSubject.analysis_id == vision_analysis.id,
                DetectedSubject.is_primary == True,
            )
            .first()
        )
        if primary_subject:
            primary_subject_info = {
                "id": primary_subject.id,
                "is_primary": True,
                "confidence": primary_subject.confidence,
            }

        face_ref = (
            db.query(FaceReference)
            .filter(FaceReference.analysis_id == vision_analysis.id)
            .order_by(FaceReference.quality_score.desc())
            .first()
        )
        if face_ref and face_ref.media_file:
            ref_path = Path(face_ref.media_file.file_path)
            if not ref_path.is_absolute():
                ref_path = get_base_storage_dir() / face_ref.media_file.file_path
            if ref_path.exists() and ref_path.is_file():
                face_ref_path = ref_path
                face_ref_present = True

    # 4. Resolve Target Scenes
    target_scenes: List[VideoScene] = []
    if scene_id:
        single_scene = (
            db.query(VideoScene)
            .filter(VideoScene.id == scene_id, VideoScene.analysis_id == video_analysis.id)
            .first()
        )
        if not single_scene:
            logger.error(f"Scene '{scene_id}' not found in analysis '{video_analysis.id}'.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SCENE_NOT_FOUND",
                    "message": f"Scene '{scene_id}' was not found in project scene analysis.",
                },
            )
        target_scenes = [single_scene]
    elif scene_ids and len(scene_ids) > 0:
        found_scenes = (
            db.query(VideoScene)
            .filter(VideoScene.id.in_(scene_ids), VideoScene.analysis_id == video_analysis.id)
            .order_by(VideoScene.sequence)
            .all()
        )
        if not found_scenes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SCENES_NOT_FOUND",
                    "message": "None of the requested scene IDs were found in the project.",
                },
            )
        target_scenes = found_scenes
    else:
        target_scenes = (
            db.query(VideoScene)
            .filter(VideoScene.analysis_id == video_analysis.id)
            .order_by(VideoScene.sequence)
            .all()
        )

    if not target_scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "NO_SCENES_AVAILABLE",
                "message": "No visual scenes available in the video analysis to generate comic frames.",
            },
        )

    # 5. Initialize Provider
    provider = get_comic_generation_provider(
        provider_name=provider_name,
        api_key=api_key,
        model=model,
        openai_client=openai_client,
    )

    # 6. Create ComicGeneration record
    generation_id = str(uuid.uuid4())
    generation_record = ComicGeneration(
        id=generation_id,
        project_id=project_id,
        provider=provider.provider_name,
        model=provider.model_name,
        status="processing",
    )
    db.add(generation_record)
    db.flush()

    # Storage output directory
    output_dir = get_project_storage_dir(project_id, "comic_frame")
    output_dir.mkdir(parents=True, exist_ok=True)
    base_storage = get_base_storage_dir()

    frames_created = 0

    try:
        # 7. Process Each Scene
        for scene in target_scenes:
            # Find keyframe for this scene
            keyframe = (
                db.query(SceneKeyframe)
                .filter(SceneKeyframe.scene_id == scene.id)
                .order_by(SceneKeyframe.timestamp)
                .first()
            )

            kf_path: Optional[Path] = None
            if keyframe and keyframe.media_file:
                kf_p = Path(keyframe.media_file.file_path)
                if not kf_p.is_absolute():
                    kf_p = base_storage / keyframe.media_file.file_path
                if kf_p.exists() and kf_p.is_file():
                    kf_path = kf_p

            timestamp = keyframe.timestamp if keyframe else scene.start_time
            prompt, prompt_ver = build_comic_generation_prompt(
                style_preset=style_preset,
                primary_subject_info=primary_subject_info,
                face_reference_present=face_ref_present,
                scene_sequence=scene.sequence + 1,
                aspect_ratio=video_analysis.aspect_ratio or "9:16",
                prompt_override=prompt_override,
            )

            frame_id = str(uuid.uuid4())
            try:
                # Call generation provider
                image_bytes, out_w, out_h = provider.generate_comic_frame(
                    prompt=prompt,
                    keyframe_path=kf_path,
                    reference_image_path=face_ref_path,
                    width=1024,
                    height=1792,
                )

                # Save generated image to storage
                stored_filename = f"{frame_id}.png"
                output_file_path = output_dir / stored_filename
                with open(output_file_path, "wb") as f:
                    f.write(image_bytes)

                file_size = len(image_bytes)
                sha256_hash = hashlib.sha256(image_bytes).hexdigest()
                rel_path = output_file_path.relative_to(base_storage).as_posix()

                # Create MediaFile DB record
                media_file_id = str(uuid.uuid4())
                media_record = MediaFile(
                    id=media_file_id,
                    project_id=project_id,
                    file_type="comic_frame",
                    original_filename=f"comic_scene_{scene.sequence + 1:02d}_{frame_id[:8]}.png",
                    stored_filename=stored_filename,
                    file_path=rel_path,
                    mime_type="image/png",
                    file_size=file_size,
                    sha256_hash=sha256_hash,
                )
                db.add(media_record)
                db.flush()

                # Create ComicFrame DB record
                frame_record = ComicFrame(
                    id=frame_id,
                    generation_id=generation_id,
                    scene_id=scene.id,
                    source_keyframe_id=keyframe.id if keyframe else None,
                    output_media_file_id=media_file_id,
                    timestamp=timestamp,
                    width=out_w,
                    height=out_h,
                    prompt_version=prompt_ver,
                    status="completed",
                    error_code=None,
                )
                db.add(frame_record)
                frames_created += 1

            except Exception as frame_err:
                logger.error(f"Failed to generate comic frame for scene {scene.id}: {frame_err}")
                # Record failed ComicFrame
                frame_record = ComicFrame(
                    id=frame_id,
                    generation_id=generation_id,
                    scene_id=scene.id,
                    source_keyframe_id=keyframe.id if keyframe else None,
                    output_media_file_id=None,
                    timestamp=timestamp,
                    width=1024,
                    height=1792,
                    prompt_version=prompt_ver,
                    status="failed",
                    error_code="GENERATION_FAILED",
                )
                db.add(frame_record)

        # 8. Update generation status
        generation_record.status = "completed" if frames_created > 0 else "failed"
        generation_record.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(generation_record)

        logger.info(
            f"Comic generation completed: id='{generation_record.id}', "
            f"provider='{provider.provider_name}', frames={frames_created}/{len(target_scenes)}"
        )
        return generation_record

    except Exception as e:
        db.rollback()
        generation_record.status = "failed"
        db.add(generation_record)
        db.commit()
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Comic generation pipeline failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "COMIC_GENERATION_FAILED",
                "message": "3D comic generation pipeline encountered an unexpected error.",
            },
        )
