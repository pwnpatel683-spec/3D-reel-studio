"""
3D Reel Studio — Final Video Compositing & 9:16 Reel Rendering Service
Phase 13: Final Video Compositing + 9:16 Reel Rendering
"""

import asyncio
import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models.project import (
    MediaFile,
    Project,
    RenderJob,
    SegmentationResult,
    ConsistencyGeneration,
    ConsistentComicFrame,
    ComicGeneration,
    ComicFrame,
    SceneKeyframe,
    VideoAnalysis,
    VideoScene,
    LyricSegment,
    LyricStyle,
    LyricAnimation,
)
from app.services.audio import resolve_ffmpeg_path, probe_video_has_audio
from app.services.analysis import resolve_ffprobe_path
from app.services.storage import (
    get_base_storage_dir,
    get_project_storage_dir,
    generate_stored_filename,
)
from app.services.lyrics import (
    KineticTextEngine,
    AnimationState,
    compute_animation_state,
    composite_text_behind_character,
    get_or_create_default_styles,
    get_or_create_default_animations,
)


# Global in-memory tracking of active render tasks for safe cancellation
_ACTIVE_RENDER_TASKS: Dict[str, asyncio.Task] = {}
_CANCELLED_JOBS: set = set()


def utc_now() -> datetime:
    """Returns current UTC timestamp timezone-aware."""
    return datetime.now(timezone.utc)


def compute_file_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hex digest of a file in streaming chunks."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def resize_and_fit_916(image: Image.Image, target_width: int = 1080, target_height: int = 1920) -> Image.Image:
    """
    Fits and centers an image into a vertical 9:16 aspect ratio canvas without stretching.
    Uses high-quality Lanczos resampling and center cropping/padding.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    target_ratio = target_width / target_height
    img_ratio = image.width / image.height

    if abs(img_ratio - target_ratio) < 0.01:
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    # If image is wider or taller, perform smart center cover crop
    if img_ratio > target_ratio:
        # Image is wider: scale height to target_height, center crop width
        new_height = target_height
        new_width = int(round(image.width * (target_height / image.height)))
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        left = (new_width - target_width) // 2
        return resized.crop((left, 0, left + target_width, target_height))
    else:
        # Image is taller/narrower: scale width to target_width, center crop height
        new_width = target_width
        new_height = int(round(image.height * (target_width / image.width)))
        resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        top = (new_height - target_height) // 2
        return resized.crop((0, top, target_width, top + target_height))


def resolve_media_file_path(file_path_str: Optional[str]) -> Optional[Path]:
    """
    Safely resolves a MediaFile path whether stored as an absolute path or relative to storage root.
    """
    if not file_path_str:
        return None
    p = Path(file_path_str)
    if p.is_file():
        return p
    base_storage = get_base_storage_dir()
    p2 = base_storage / file_path_str
    if p2.is_file():
        return p2
    return None


def find_scene_visual_assets(db: Session, project_id: str, scene: VideoScene) -> Dict[str, Optional[Path]]:
    """
    Discovers the best layered or flattened visual assets available for a scene:
    1. Phase 11 SegmentationResult (Foreground RGBA + Background + Alpha Mask)
    2. Phase 10 ConsistentComicFrame
    3. Phase 9 ComicFrame
    4. Phase 7 SceneKeyframe
    """
    base_storage = get_base_storage_dir()
    assets: Dict[str, Optional[Path]] = {
        "background_path": None,
        "foreground_path": None,
        "mask_path": None,
        "composite_path": None,
        "base_image_path": None,
    }

    # 1. Try Phase 11 SegmentationResult
    seg_result = (
        db.query(SegmentationResult)
        .filter(
            SegmentationResult.project_id == project_id,
            SegmentationResult.source_scene_id == scene.id,
            SegmentationResult.status == "completed",
        )
        .order_by(SegmentationResult.created_at.desc())
        .first()
    )

    if seg_result:
        if seg_result.background_media_file_id:
            bg_mf = db.query(MediaFile).filter(MediaFile.id == seg_result.background_media_file_id).first()
            if bg_mf:
                assets["background_path"] = resolve_media_file_path(bg_mf.file_path)

        if seg_result.foreground_media_file_id:
            fg_mf = db.query(MediaFile).filter(MediaFile.id == seg_result.foreground_media_file_id).first()
            if fg_mf:
                assets["foreground_path"] = resolve_media_file_path(fg_mf.file_path)

        if seg_result.mask_media_file_id:
            mask_mf = db.query(MediaFile).filter(MediaFile.id == seg_result.mask_media_file_id).first()
            if mask_mf:
                assets["mask_path"] = resolve_media_file_path(mask_mf.file_path)

        if seg_result.composite_media_file_id:
            comp_mf = db.query(MediaFile).filter(MediaFile.id == seg_result.composite_media_file_id).first()
            if comp_mf:
                resolved_comp = resolve_media_file_path(comp_mf.file_path)
                assets["composite_path"] = resolved_comp
                assets["base_image_path"] = resolved_comp

    # 2. Try Phase 10 ConsistentComicFrame if no base path found
    if not assets["base_image_path"]:
        consistent_frame = (
            db.query(ConsistentComicFrame)
            .join(ConsistencyGeneration, ConsistentComicFrame.consistency_generation_id == ConsistencyGeneration.id)
            .filter(
                ConsistencyGeneration.project_id == project_id,
                ConsistentComicFrame.scene_id == scene.id,
                ConsistentComicFrame.status == "completed",
            )
            .order_by(ConsistentComicFrame.created_at.desc())
            .first()
        )
        if consistent_frame and consistent_frame.output_media_file_id:
            cf_mf = db.query(MediaFile).filter(MediaFile.id == consistent_frame.output_media_file_id).first()
            if cf_mf:
                assets["base_image_path"] = resolve_media_file_path(cf_mf.file_path)

    # 3. Try Phase 9 ComicFrame if no base path found
    if not assets["base_image_path"]:
        comic_frame = (
            db.query(ComicFrame)
            .join(ComicGeneration, ComicFrame.generation_id == ComicGeneration.id)
            .filter(
                ComicGeneration.project_id == project_id,
                ComicFrame.scene_id == scene.id,
                ComicFrame.status == "completed",
            )
            .order_by(ComicFrame.created_at.desc())
            .first()
        )
        if comic_frame and comic_frame.output_media_file_id:
            cmf_mf = db.query(MediaFile).filter(MediaFile.id == comic_frame.output_media_file_id).first()
            if cmf_mf:
                assets["base_image_path"] = resolve_media_file_path(cmf_mf.file_path)

    # 4. Fallback to Phase 7 Keyframe
    if not assets["base_image_path"]:
        kf = (
            db.query(SceneKeyframe)
            .filter(SceneKeyframe.scene_id == scene.id)
            .order_by(SceneKeyframe.timestamp.asc())
            .first()
        )
        if kf and kf.media_file_id:
            kf_mf = db.query(MediaFile).filter(MediaFile.id == kf.media_file_id).first()
            if kf_mf:
                assets["base_image_path"] = resolve_media_file_path(kf_mf.file_path)

    return assets


def get_overlapping_lyrics_for_scene(db: Session, project_id: str, start_time: float, end_time: float) -> List[LyricSegment]:
    """
    Returns all enabled lyric segments overlapping with the scene timeframe.
    """
    return (
        db.query(LyricSegment)
        .filter(
            LyricSegment.project_id == project_id,
            LyricSegment.enabled == True,
            LyricSegment.start_time < end_time,
            LyricSegment.end_time > start_time,
        )
        .order_by(LyricSegment.sequence.asc())
        .all()
    )


class ReelCompositingEngine:
    """
    Compositing engine that renders intermediate scene video clips and assembles the final 9:16 Reel.
    """

    def __init__(
        self,
        output_width: int = 1080,
        output_height: int = 1920,
        fps: float = 30.0,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
    ):
        self.output_width = output_width
        self.output_height = output_height
        self.fps = fps
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.ffmpeg_bin = resolve_ffmpeg_path()
        self.ffprobe_bin = resolve_ffprobe_path()

    def render_scene_clip(
        self,
        db: Session,
        project_id: str,
        scene: VideoScene,
        scene_idx: int,
        temp_dir: Path,
        include_lyrics: bool = True,
    ) -> Path:
        """
        Renders a single scene into an intermediate MP4 video clip at the target 9:16 resolution.
        Applies kinetic typography and soft alpha text-behind-character compositing when lyrics overlap.
        """
        if not self.ffmpeg_bin:
            raise RuntimeError("FFmpeg executable not found on system.")

        scene_start = max(0.0, float(scene.start_time))
        scene_end = max(scene_start + 0.1, float(scene.end_time))
        duration = max(0.1, scene_end - scene_start)

        assets = find_scene_visual_assets(db, project_id, scene)
        has_layers = (
            assets["background_path"] is not None
            and assets["foreground_path"] is not None
            and assets["background_path"].is_file()
            and assets["foreground_path"].is_file()
        )

        base_img_path = assets["base_image_path"] or assets["composite_path"] or assets["background_path"]
        if not base_img_path and not has_layers:
            # Generate a solid neutral frame if no visual exists
            base_canvas = Image.new("RGBA", (self.output_width, self.output_height), (18, 20, 29, 255))
        else:
            base_canvas = None

        overlapping_lyrics = []
        if include_lyrics:
            overlapping_lyrics = get_overlapping_lyrics_for_scene(db, project_id, scene_start, scene_end)

        scene_out_path = temp_dir / f"scene_{scene_idx:03d}.mp4"

        # OPTIMIZATION: If no lyrics active in this scene, render a single still 9:16 frame and loop with FFmpeg
        if not overlapping_lyrics:
            single_frame_path = temp_dir / f"still_{scene_idx:03d}.png"
            if has_layers and assets["background_path"] and assets["foreground_path"]:
                bg_img = Image.open(assets["background_path"]).convert("RGBA")
                fg_img = Image.open(assets["foreground_path"]).convert("RGBA")
                comp = Image.alpha_composite(bg_img, fg_img)
            elif base_img_path and base_img_path.is_file():
                comp = Image.open(base_img_path).convert("RGBA")
            else:
                comp = base_canvas

            fitted_comp = resize_and_fit_916(comp, self.output_width, self.output_height)
            fitted_comp.convert("RGB").save(single_frame_path, format="PNG")

            # Encode single image loop to MP4
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(self.fps),
                "-t",
                f"{duration:.4f}",
                "-i",
                str(single_frame_path),
                "-c:v",
                self.video_codec,
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(self.fps),
                "-movflags",
                "+faststart",
                str(scene_out_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=settings.RENDER_TIMEOUT_SECONDS)
            if res.returncode != 0 or not scene_out_path.is_file():
                logger.error(f"FFmpeg error encoding still scene {scene_idx}: {res.stderr}")
                raise RuntimeError(f"FFmpeg failed encoding scene {scene_idx}: {res.stderr[:200]}")

            return scene_out_path

        # DYNAMIC PATH: Scene has active kinetic lyrics. Render frame sequence at target FPS.
        frames_dir = temp_dir / f"frames_scene_{scene_idx:03d}"
        frames_dir.mkdir(parents=True, exist_ok=True)

        # Pre-load base/layered assets
        bg_pil = Image.open(assets["background_path"]).convert("RGBA") if has_layers and assets["background_path"] else None
        fg_pil = Image.open(assets["foreground_path"]).convert("RGBA") if has_layers and assets["foreground_path"] else None
        base_pil = Image.open(base_img_path).convert("RGBA") if (not has_layers and base_img_path and base_img_path.is_file()) else base_canvas

        ref_width = (bg_pil or base_pil).width
        ref_height = (bg_pil or base_pil).height

        num_frames = max(1, int(math.ceil(duration * self.fps)))

        for frame_i in range(num_frames):
            frame_t = scene_start + (frame_i / self.fps)

            # Find active lyric segment at current timestamp
            active_lyric = next(
                (l for l in overlapping_lyrics if l.start_time <= frame_t <= l.end_time),
                None,
            )

            if active_lyric:
                style_obj = active_lyric.style
                if not style_obj:
                    style_obj = LyricStyle(
                        name="DEFAULT",
                        font_family="Outfit",
                        font_size=64,
                        font_weight="bold",
                        fill_color="#FFFFFF",
                        outline_color="#000000",
                        outline_width=4,
                        shadow_color="rgba(0,0,0,0.8)",
                        shadow_offset_x=4,
                        shadow_offset_y=4,
                        shadow_blur=8,
                        letter_spacing=2,
                        line_spacing=1.15,
                        text_transform="uppercase",
                        alignment="center",
                    )

                anim_obj = active_lyric.animation
                anim_type = anim_obj.animation_type if anim_obj else "POP"
                anim_dur = anim_obj.duration if anim_obj else 0.35

                seg_dur = max(0.01, active_lyric.end_time - active_lyric.start_time)
                progress = max(0.0, min(1.0, (frame_t - active_lyric.start_time) / seg_dur))

                anim_state = compute_animation_state(
                    animation_type=anim_type,
                    progress=progress,
                    anim_duration=anim_dur,
                    segment_duration=seg_dur,
                    current_time=frame_t,
                    start_time=active_lyric.start_time,
                )

                text_layer = KineticTextEngine.render_text_layer(
                    text=active_lyric.text,
                    canvas_width=ref_width,
                    canvas_height=ref_height,
                    style=style_obj,
                    anim_state=anim_state,
                    pos_x=active_lyric.position_x if active_lyric.position_x is not None else 0.5,
                    pos_y=active_lyric.position_y if active_lyric.position_y is not None else 0.75,
                    scale_override=active_lyric.scale if active_lyric.scale is not None else 1.0,
                    rotation_override=active_lyric.rotation if active_lyric.rotation is not None else 0.0,
                    opacity_override=active_lyric.opacity if active_lyric.opacity is not None else 1.0,
                )

                if has_layers and bg_pil and fg_pil:
                    composite_frame = composite_text_behind_character(
                        bg_image=bg_pil,
                        text_layer=text_layer,
                        fg_image=fg_pil,
                    )
                else:
                    composite_frame = Image.alpha_composite(base_pil.copy(), text_layer)
            else:
                if has_layers and bg_pil and fg_pil:
                    composite_frame = Image.alpha_composite(bg_pil.copy(), fg_pil)
                else:
                    composite_frame = base_pil.copy()

            fitted_frame = resize_and_fit_916(composite_frame, self.output_width, self.output_height)
            frame_path = frames_dir / f"frame_{frame_i:06d}.png"
            fitted_frame.convert("RGB").save(frame_path, format="PNG")

        # Encode frame sequence into scene video clip via FFmpeg
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-framerate",
            str(self.fps),
            "-i",
            str(frames_dir / "frame_%06d.png"),
            "-c:v",
            self.video_codec,
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.fps),
            "-movflags",
            "+faststart",
            str(scene_out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=settings.RENDER_TIMEOUT_SECONDS)
        if res.returncode != 0 or not scene_out_path.is_file():
            logger.error(f"FFmpeg error compiling kinetic scene {scene_idx}: {res.stderr}")
            raise RuntimeError(f"FFmpeg failed compiling kinetic frames for scene {scene_idx}: {res.stderr[:200]}")

        return scene_out_path

    def concatenate_scene_clips(self, scene_paths: List[Path], temp_dir: Path) -> Path:
        """
        Concatenates intermediate scene MP4 clips into a seamless single video track.
        """
        if not self.ffmpeg_bin:
            raise RuntimeError("FFmpeg executable not found on system.")

        if not scene_paths:
            raise ValueError("No scene clips provided for concatenation.")

        if len(scene_paths) == 1:
            concat_video_path = temp_dir / "concat_video.mp4"
            shutil.copyfile(scene_paths[0], concat_video_path)
            return concat_video_path

        manifest_path = temp_dir / "concat_manifest.txt"
        with open(manifest_path, "w", encoding="utf-8") as f:
            for sp in scene_paths:
                f.write(f"file '{sp.as_posix()}'\n")

        concat_video_path = temp_dir / "concat_video.mp4"
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-c:v",
            self.video_codec,
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.fps),
            str(concat_video_path),
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=settings.RENDER_TIMEOUT_SECONDS)
        if res.returncode != 0 or not concat_video_path.is_file():
            logger.error(f"FFmpeg error concatenating scene clips: {res.stderr}")
            raise RuntimeError(f"FFmpeg concatenation failed: {res.stderr[:200]}")

        return concat_video_path

    def mux_audio_track(
        self,
        video_path: Path,
        audio_path: Optional[Path],
        total_duration: float,
        temp_dir: Path,
    ) -> Path:
        """
        Multiplexes extracted or source audio with the concatenated video track.
        Produces the final MP4 Reel with synced AAC audio.
        """
        if not self.ffmpeg_bin:
            raise RuntimeError("FFmpeg executable not found on system.")

        final_out_path = temp_dir / "final_reel_output.mp4"

        if audio_path and audio_path.is_file():
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-c:v",
                "copy",
                "-c:a",
                self.audio_codec,
                "-b:a",
                "192k",
                "-ar",
                "44100",
                "-t",
                f"{total_duration:.4f}",
                "-movflags",
                "+faststart",
                str(final_out_path),
            ]
        else:
            # No audio available: output clean video track
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(video_path),
                "-c:v",
                "copy",
                "-t",
                f"{total_duration:.4f}",
                "-movflags",
                "+faststart",
                str(final_out_path),
            ]

        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=settings.RENDER_TIMEOUT_SECONDS)
        if res.returncode != 0 or not final_out_path.is_file():
            logger.error(f"FFmpeg error during final audio muxing: {res.stderr}")
            raise RuntimeError(f"FFmpeg audio mux failed: {res.stderr[:200]}")

        return final_out_path

    def validate_output_mp4(self, mp4_path: Path, expected_audio: bool = True) -> Dict[str, Any]:
        """
        Validates that the rendered file is a valid, non-empty 9:16 MP4 container with correct streams.
        """
        if not mp4_path.is_file():
            raise ValueError("Rendered MP4 file does not exist on disk.")

        file_size = mp4_path.stat().st_size
        if file_size == 0:
            raise ValueError("Rendered MP4 file is empty (0 bytes).")

        if not self.ffprobe_bin:
            # If ffprobe is unavailable, return basic metadata
            return {
                "file_size": file_size,
                "width": self.output_width,
                "height": self.output_height,
                "fps": self.fps,
                "duration": None,
                "video_codec": self.video_codec,
                "audio_codec": self.audio_codec if expected_audio else None,
            }

        cmd = [
            self.ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(mp4_path),
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        if res.returncode != 0 or not res.stdout:
            raise ValueError(f"FFprobe failed to inspect output MP4: {res.stderr}")

        try:
            info = json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise ValueError(f"FFprobe output could not be parsed: {e}")

        streams = info.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        if not v_stream:
            raise ValueError("Output MP4 is missing a video stream.")

        actual_w = int(v_stream.get("width", 0))
        actual_h = int(v_stream.get("height", 0))
        if actual_w != self.output_width or actual_h != self.output_height:
            raise ValueError(f"Output dimensions ({actual_w}x{actual_h}) do not match target ({self.output_width}x{self.output_height}).")

        fmt = info.get("format", {})
        duration = float(fmt.get("duration", 0.0))

        return {
            "file_size": file_size,
            "width": actual_w,
            "height": actual_h,
            "duration": duration,
            "video_codec": v_stream.get("codec_name", "h264"),
            "audio_codec": a_stream.get("codec_name") if a_stream else None,
            "has_audio": a_stream is not None,
        }


def run_final_reel_render_sync(
    db: Session,
    project_id: str,
    job_id: str,
    output_width: int = 1080,
    output_height: int = 1920,
    fps: float = 30.0,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    include_audio: bool = True,
    include_lyrics: bool = True,
) -> RenderJob:
    """
    Synchronous orchestrator for rendering a final 9:16 vertical Reel.
    Executes scene-by-scene compositing, concatenation, audio multiplexing, and validation.
    """
    clean_proj_id = project_id.strip()
    job = db.query(RenderJob).filter(RenderJob.id == job_id).first()
    if not job:
        raise ValueError(f"Render job '{job_id}' not found.")

    if job.id in _CANCELLED_JOBS:
        job.status = "cancelled"
        job.stage_message = "Render job cancelled by user."
        db.commit()
        return job

    job.status = "processing"
    job.started_at = utc_now()
    job.progress = 0.05
    job.stage_message = "Initializing scene timeline and visual assets..."
    db.commit()

    # Discover source video
    source_media = (
        db.query(MediaFile)
        .filter(MediaFile.project_id == clean_proj_id, MediaFile.file_type == "source_video")
        .first()
    )
    source_video_path = resolve_media_file_path(source_media.file_path) if source_media else None
    if not source_video_path:
        job.status = "failed"
        job.error_code = "SOURCE_VIDEO_MISSING"
        job.error_message = "Source video not found on disk."
        db.commit()
        raise ValueError("Source video is missing for project.")

    # Discover scenes
    scenes = (
        db.query(VideoScene)
        .join(VideoAnalysis, VideoScene.analysis_id == VideoAnalysis.id)
        .filter(VideoAnalysis.project_id == clean_proj_id)
        .order_by(VideoScene.sequence.asc())
        .all()
    )

    if not scenes:
        # If no scenes found, construct a default full-duration scene
        va = db.query(VideoAnalysis).filter(VideoAnalysis.project_id == clean_proj_id).first()
        va_id = va.id if va else f"va-default-{uuid.uuid4().hex[:6]}"
        default_scene = VideoScene(
            id=f"scene-default-{uuid.uuid4().hex[:6]}",
            analysis_id=va_id,
            sequence=0,
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
        )
        scenes = [default_scene]

    total_duration = sum(s.duration for s in scenes)
    if total_duration <= 0:
        total_duration = max(scenes[-1].end_time, 3.0)

    # Discover extracted audio file if requested
    audio_path = None
    if include_audio:
        audio_media = (
            db.query(MediaFile)
            .filter(MediaFile.project_id == clean_proj_id, MediaFile.file_type == "extracted_audio")
            .order_by(MediaFile.created_at.desc())
            .first()
        )
        if audio_media:
            audio_path = resolve_media_file_path(audio_media.file_path)
        if not audio_path and source_video_path and probe_video_has_audio(source_video_path, resolve_ffmpeg_path() or "ffmpeg"):
            audio_path = source_video_path

    # Prepare isolated temporary working directory
    base_storage = get_base_storage_dir()
    temp_dir = base_storage / "projects" / clean_proj_id / "renders" / f"tmp_job_{job.id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    engine = ReelCompositingEngine(
        output_width=output_width,
        output_height=output_height,
        fps=fps,
        video_codec=video_codec,
        audio_codec=audio_codec,
    )

    scene_clips: List[Path] = []

    try:
        # 1. Render intermediate clips for each scene
        num_scenes = len(scenes)
        for idx, scene in enumerate(scenes):
            if job.id in _CANCELLED_JOBS:
                job.status = "cancelled"
                job.stage_message = "Render cancelled during scene compositing."
                db.commit()
                return job

            progress_val = 0.1 + (0.65 * (idx / num_scenes))
            job.progress = round(progress_val, 2)
            job.stage_message = f"Compositing scene {idx + 1}/{num_scenes} (t={scene.start_time:.1f}s - {scene.end_time:.1f}s)..."
            db.commit()

            clip_path = engine.render_scene_clip(
                db=db,
                project_id=clean_proj_id,
                scene=scene,
                scene_idx=idx,
                temp_dir=temp_dir,
                include_lyrics=include_lyrics,
            )
            scene_clips.append(clip_path)

        # 2. Concatenate scene clips
        job.progress = 0.80
        job.stage_message = "Concatenating scene clips into seamless video track..."
        db.commit()

        concat_video = engine.concatenate_scene_clips(scene_clips, temp_dir)

        # 3. Multiplex audio track
        job.progress = 0.88
        job.stage_message = "Multiplexing synchronized audio track..."
        db.commit()

        final_temp_mp4 = engine.mux_audio_track(concat_video, audio_path, total_duration, temp_dir)

        # 4. Output validation
        job.progress = 0.94
        job.stage_message = "Validating final 9:16 MP4 Reel..."
        db.commit()

        val_meta = engine.validate_output_mp4(final_temp_mp4, expected_audio=bool(audio_path))

        # 5. Move to permanent project storage
        final_storage_dir = get_project_storage_dir(clean_proj_id, "final_reel")
        final_storage_dir.mkdir(parents=True, exist_ok=True)
        stored_filename = generate_stored_filename(".mp4")
        permanent_mp4_path = final_storage_dir / stored_filename
        shutil.copyfile(final_temp_mp4, permanent_mp4_path)

        sha256_hash = compute_file_sha256(permanent_mp4_path)
        file_size = permanent_mp4_path.stat().st_size

        # Create MediaFile record
        output_mf = MediaFile(
            project_id=clean_proj_id,
            file_type="final_reel",
            original_filename=f"{clean_proj_id}_3D_Reel.mp4",
            stored_filename=stored_filename,
            file_path=str(permanent_mp4_path),
            mime_type="video/mp4",
            file_size=file_size,
            sha256_hash=sha256_hash,
        )
        db.add(output_mf)
        db.flush()

        # Update Job record
        job.status = "completed"
        job.progress = 1.0
        job.stage_message = "Final 9:16 Reel render complete."
        job.output_media_file_id = output_mf.id
        job.duration = val_meta.get("duration") or total_duration
        job.render_metadata = val_meta
        job.completed_at = utc_now()
        db.commit()
        db.refresh(job)

        logger.info(f"Final Reel render job {job.id} completed successfully: {permanent_mp4_path} ({file_size} bytes)")
        return job

    except Exception as e:
        logger.error(f"Render job {job.id} failed: {e}", exc_info=True)
        job.status = "failed"
        job.error_code = "RENDER_EXECUTION_FAILED"
        job.error_message = str(e)
        job.stage_message = f"Render failed: {str(e)[:100]}"
        db.commit()
        raise e
    finally:
        # Clean temporary working directory
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_err:
            logger.warning(f"Error cleaning render temp dir {temp_dir}: {cleanup_err}")


def cancel_render_job(db: Session, project_id: str, job_id: str) -> RenderJob:
    """
    Cancels an active or queued render job and cleans up resources.
    """
    clean_proj_id = project_id.strip()
    job = db.query(RenderJob).filter(RenderJob.id == job_id, RenderJob.project_id == clean_proj_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RENDER_JOB_NOT_FOUND", "message": f"Render job '{job_id}' not found."},
        )

    if job.status in ("completed", "cancelled"):
        return job

    _CANCELLED_JOBS.add(job.id)

    # Cancel asyncio task if running in background
    if job.id in _ACTIVE_RENDER_TASKS:
        task = _ACTIVE_RENDER_TASKS.pop(job.id, None)
        if task and not task.done():
            task.cancel()

    job.status = "cancelled"
    job.stage_message = "Render cancelled by user."
    job.updated_at = utc_now()
    db.commit()
    db.refresh(job)

    # Clean temporary files if exist
    base_storage = get_base_storage_dir()
    temp_dir = base_storage / "projects" / clean_proj_id / "renders" / f"tmp_job_{job.id}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    return job
