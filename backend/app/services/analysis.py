"""
3D Reel Studio — Video Scene & Content Analysis Service
Phase 7: Video Scene & Content Analysis
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.services.audio import resolve_ffmpeg_path
from app.services.storage import get_base_storage_dir, generate_stored_filename


@dataclass
class VideoMetadata:
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: Optional[str]
    pixel_format: Optional[str]
    aspect_ratio: str


@dataclass
class KeyframeData:
    timestamp: float
    stored_filename: str
    relative_path: str
    file_size: int
    sha256_hash: str
    width: int
    height: int


@dataclass
class SceneData:
    sequence: int
    start_time: float
    end_time: float
    duration: float
    keyframe: Optional[KeyframeData] = None


@dataclass
class AnalysisResult:
    metadata: VideoMetadata
    scenes: List[SceneData]


def get_project_keyframes_dir(project_id: str) -> Path:
    """
    Returns the isolated storage directory for a project's extracted scene keyframes.
    Enforces strict path traversal prevention.
    """
    clean_id = project_id.strip()
    if (
        not clean_id
        or ".." in clean_id
        or "/" in clean_id
        or "\\" in clean_id
        or clean_id.startswith(".")
    ):
        logger.warning(f"Path traversal attempt rejected for keyframe storage: '{project_id}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project identifier (path traversal prohibited).",
        )

    base_storage = get_base_storage_dir()
    keyframes_dir = base_storage / "projects" / clean_id / "keyframes"

    try:
        resolved_dir = keyframes_dir.resolve()
        resolved_base = base_storage.resolve()
        if not str(resolved_dir).startswith(str(resolved_base)):
            raise ValueError("Resolved keyframes path falls outside base storage directory.")
    except Exception as e:
        logger.error(f"Security error validating keyframes directory path: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project path identifiers.",
        )

    keyframes_dir.mkdir(parents=True, exist_ok=True)
    return keyframes_dir


def resolve_ffprobe_path() -> Optional[str]:
    """
    Resolves the system or configured FFprobe executable path.
    Checks next to the resolved FFmpeg executable, system PATH, and standard directories.
    """
    ffmpeg_path = resolve_ffmpeg_path()
    if ffmpeg_path:
        ffmpeg_p = Path(ffmpeg_path)
        candidate = ffmpeg_p.parent / ("ffprobe.exe" if ffmpeg_p.suffix.lower() == ".exe" else "ffprobe")
        if candidate.is_file():
            return str(candidate)

    which_probe = shutil.which("ffprobe")
    if which_probe:
        return which_probe

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            for ffprobe_exe in winget_pkgs.glob("**/ffprobe.exe"):
                if ffprobe_exe.is_file():
                    return str(ffprobe_exe)

    return None


def calculate_aspect_ratio_label(width: int, height: int) -> str:
    """
    Calculates a standard or reduced aspect ratio string (e.g. '9:16', '16:9', '1:1', '4:5').
    """
    if width <= 0 or height <= 0:
        return "9:16"

    ratio = width / height

    # Match common standard vertical & horizontal video aspect ratios with slight tolerance
    if abs(ratio - 9 / 16) < 0.02:
        return "9:16"
    if abs(ratio - 16 / 9) < 0.02:
        return "16:9"
    if abs(ratio - 1.0) < 0.02:
        return "1:1"
    if abs(ratio - 4 / 5) < 0.02:
        return "4:5"
    if abs(ratio - 4 / 3) < 0.02:
        return "4:3"

    gcd_val = math.gcd(width, height)
    if gcd_val > 1 and (width // gcd_val) < 100:
        return f"{width // gcd_val}:{height // gcd_val}"

    return f"{round(ratio, 2)}:1"


def extract_video_metadata(video_path: Path) -> VideoMetadata:
    """
    Extracts reliable video stream metadata using FFprobe / FFmpeg.
    Returns width, height, fps, frame count, duration, codec, pixel format, and aspect ratio.
    """
    ffprobe_bin = resolve_ffprobe_path()
    ffmpeg_bin = resolve_ffmpeg_path()

    if not ffprobe_bin and not ffmpeg_bin:
        logger.error("Neither FFprobe nor FFmpeg could be resolved on the system.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "FFMPEG_UNAVAILABLE",
                "message": "FFmpeg/FFprobe media tools are not available on the server.",
            },
        )

    # 1. Try ffprobe JSON probe first
    if ffprobe_bin:
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration,codec_name,pix_fmt",
            "-show_entries", "format=duration",
            "-of", "json",
            str(video_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                timeout=20,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                streams = data.get("streams", [])
                format_info = data.get("format", {})

                if streams:
                    v_stream = streams[0]
                    width = int(v_stream.get("width") or 0)
                    height = int(v_stream.get("height") or 0)
                    codec = v_stream.get("codec_name")
                    pix_fmt = v_stream.get("pix_fmt")

                    # Parse FPS
                    fps = 30.0
                    fps_str = v_stream.get("avg_frame_rate") or v_stream.get("r_frame_rate") or ""
                    if "/" in fps_str:
                        num, den = fps_str.split("/", 1)
                        try:
                            num_f, den_f = float(num), float(den)
                            if den_f > 0:
                                fps = round(num_f / den_f, 2)
                        except ValueError:
                            pass
                    elif fps_str:
                        try:
                            fps = round(float(fps_str), 2)
                        except ValueError:
                            pass

                    # Parse Duration
                    duration = 0.0
                    dur_str = v_stream.get("duration") or format_info.get("duration")
                    if dur_str:
                        try:
                            duration = round(float(dur_str), 3)
                        except ValueError:
                            pass

                    # Parse Frame Count
                    nb_frames_str = v_stream.get("nb_frames")
                    if nb_frames_str:
                        try:
                            frame_count = int(nb_frames_str)
                        except ValueError:
                            frame_count = max(1, int(round(duration * fps)))
                    else:
                        frame_count = max(1, int(round(duration * fps)))

                    if width > 0 and height > 0:
                        aspect_ratio = calculate_aspect_ratio_label(width, height)
                        return VideoMetadata(
                            width=width,
                            height=height,
                            fps=fps,
                            frame_count=frame_count,
                            duration=duration,
                            codec=codec,
                            pixel_format=pix_fmt,
                            aspect_ratio=aspect_ratio,
                        )
        except Exception as e:
            logger.warning(f"FFprobe JSON extraction failed or timed out, falling back to FFmpeg banner parse: {e}")

    # 2. Fallback to FFmpeg banner inspection
    if ffmpeg_bin:
        cmd = [ffmpeg_bin, "-hide_banner", "-i", str(video_path)]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                timeout=15,
            )
            output = proc.stderr

            # Regex for resolution: e.g. 1080x1920 or 1920x1080
            res_match = re.search(r"(\d{2,5})x(\d{2,5})", output)
            width = int(res_match.group(1)) if res_match else 1080
            height = int(res_match.group(2)) if res_match else 1920

            # Regex for FPS: e.g. 30 fps, 29.97 fps
            fps_match = re.search(r"([\d\.]+)\s*fps", output)
            fps = float(fps_match.group(1)) if fps_match else 30.0

            # Regex for Duration: e.g. Duration: 00:00:10.50
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d\.]+)", output)
            if dur_match:
                hours = float(dur_match.group(1))
                mins = float(dur_match.group(2))
                secs = float(dur_match.group(3))
                duration = round(hours * 3600 + mins * 60 + secs, 3)
            else:
                duration = 1.0

            # Regex for Codec: e.g. Video: h264 or Video: hevc
            codec_match = re.search(r"Video:\s*([a-zA-Z0-9_-]+)", output)
            codec = codec_match.group(1) if codec_match else "h264"

            # Regex for Pixel Format: e.g. yuv420p
            pix_match = re.search(r"Video:.*?([a-zA-Z0-9_]+)\(?", output)
            pix_fmt = pix_match.group(1) if pix_match else "yuv420p"

            frame_count = max(1, int(round(duration * fps)))
            aspect_ratio = calculate_aspect_ratio_label(width, height)

            return VideoMetadata(
                width=width,
                height=height,
                fps=fps,
                frame_count=frame_count,
                duration=duration,
                codec=codec,
                pixel_format=pix_fmt,
                aspect_ratio=aspect_ratio,
            )
        except Exception as err:
            logger.error(f"FFmpeg fallback banner probe failed: {err}")

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "INVALID_VIDEO_METADATA",
            "message": "Failed to parse video stream metadata. The file may be corrupt or an unsupported container.",
        },
    )


def detect_video_scenes(
    video_path: Path,
    duration: float,
    fps: float,
    threshold: float = 0.30,
    min_scene_duration: float = 0.8,
) -> List[Tuple[float, float]]:
    """
    Detects visual shot and scene transitions using FFmpeg's scene change detection filter.
    Returns list of (start_time, end_time) boundaries.
    """
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FFMPEG_UNAVAILABLE", "message": "FFmpeg executable is not available on the server."},
        )

    # If the video is very short, treat entire video as a single scene
    if duration <= min_scene_duration * 1.5:
        return [(0.0, round(duration, 3))]

    cut_timestamps: List[float] = []

    # Run FFmpeg scene change filter
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-i", str(video_path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-",
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=60,
        )
        output = proc.stderr

        # Parse pts_time occurrences
        # e.g., [Parsed_showinfo_1 @ ...] n: ... pts_time:3.42 ...
        for match in re.finditer(r"pts_time:([0-9\.]+)", output):
            try:
                t = float(match.group(1))
                if 0.2 < t < (duration - 0.2):
                    cut_timestamps.append(t)
            except ValueError:
                pass
    except Exception as e:
        logger.warning(f"Scene detection filter execution encountered error (using single scene fallback): {e}")

    # Deduplicate and filter cut points by min_scene_duration
    filtered_cuts: List[float] = []
    last_cut = 0.0

    for t in sorted(cut_timestamps):
        if (t - last_cut) >= min_scene_duration and (duration - t) >= (min_scene_duration / 2.0):
            filtered_cuts.append(round(t, 3))
            last_cut = t

    # Build contiguous scene segments
    scenes: List[Tuple[float, float]] = []
    prev_time = 0.0

    for cut_t in filtered_cuts:
        scenes.append((prev_time, cut_t))
        prev_time = cut_t

    scenes.append((prev_time, round(duration, 3)))
    return scenes


def extract_keyframe_image(
    video_path: Path,
    timestamp: float,
    output_image_path: Path,
    width: int,
    height: int,
) -> KeyframeData:
    """
    Extracts a representative visual keyframe image from the video at the given timestamp using FFmpeg.
    """
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "FFMPEG_UNAVAILABLE", "message": "FFmpeg executable is not available on the server."},
        )

    # Safe timestamp seek
    safe_ts = max(0.0, timestamp)

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-ss", f"{safe_ts:.3f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",  # High JPEG quality
        str(output_image_path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=20,
        )
        if proc.returncode != 0 or not output_image_path.exists() or output_image_path.stat().st_size == 0:
            logger.error(f"FFmpeg keyframe extraction failed: {proc.stderr}")
            raise RuntimeError(f"FFmpeg keyframe generation failed for timestamp {safe_ts}s")
    except Exception as e:
        logger.error(f"Keyframe extraction error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "KEYFRAME_EXTRACTION_FAILED",
                "message": f"Failed to extract keyframe at timestamp {safe_ts:.2f}s.",
            },
        )

    file_bytes = output_image_path.read_bytes()
    file_size = len(file_bytes)
    sha256_hex = hashlib.sha256(file_bytes).hexdigest()

    return KeyframeData(
        timestamp=safe_ts,
        stored_filename=output_image_path.name,
        relative_path="",  # Filled by caller
        file_size=file_size,
        sha256_hash=sha256_hex,
        width=width,
        height=height,
    )


def analyze_video_pipeline(
    project_id: str,
    video_path: Path,
) -> AnalysisResult:
    """
    Complete Video Analysis Pipeline:
    1. Validates physical source video existence and size
    2. Extracts structured video stream metadata
    3. Detects scene boundaries
    4. Extracts representative keyframe images near each scene's midpoint
    """
    if not video_path.exists() or not video_path.is_file():
        logger.error(f"Physical source video missing on disk: {video_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "VIDEO_FILE_NOT_FOUND",
                "message": "Physical video file is missing on the server disk.",
            },
        )

    file_size = video_path.stat().st_size
    if file_size == 0:
        logger.error("Source video is empty (0 bytes).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EMPTY_VIDEO_FILE",
                "message": "Source video file is empty (0 bytes) and cannot be analyzed.",
            },
        )

    logger.info(f"Starting video analysis for project='{project_id}', video_size={file_size}B")

    # 1. Metadata Extraction
    metadata = extract_video_metadata(video_path)
    logger.info(
        f"Video metadata extracted: {metadata.width}x{metadata.height}, {metadata.fps}fps, "
        f"dur={metadata.duration}s, ratio={metadata.aspect_ratio}, codec={metadata.codec}"
    )

    # Validate video metadata against production limits
    if metadata.duration > settings.SOURCE_VIDEO_MAX_DURATION_SECONDS:
        logger.warning(f"Video duration ({metadata.duration}s) exceeds maximum ({settings.SOURCE_VIDEO_MAX_DURATION_SECONDS}s).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VIDEO_DURATION_EXCEEDED",
                "message": f"Source video duration ({metadata.duration:.1f}s) exceeds the maximum allowed duration of {settings.SOURCE_VIDEO_MAX_DURATION_SECONDS:.0f}s.",
            },
        )

    if metadata.width > settings.SOURCE_VIDEO_MAX_WIDTH or metadata.height > settings.SOURCE_VIDEO_MAX_HEIGHT:
        logger.warning(f"Video resolution ({metadata.width}x{metadata.height}) exceeds max ({settings.SOURCE_VIDEO_MAX_WIDTH}x{settings.SOURCE_VIDEO_MAX_HEIGHT}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VIDEO_RESOLUTION_EXCEEDED",
                "message": f"Source video resolution ({metadata.width}x{metadata.height}) exceeds maximum allowed dimensions ({settings.SOURCE_VIDEO_MAX_WIDTH}x{settings.SOURCE_VIDEO_MAX_HEIGHT}).",
            },
        )

    if metadata.fps > settings.SOURCE_VIDEO_MAX_FPS:
        logger.warning(f"Video FPS ({metadata.fps}) exceeds maximum ({settings.SOURCE_VIDEO_MAX_FPS}).")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VIDEO_FPS_EXCEEDED",
                "message": f"Source video frame rate ({metadata.fps} fps) exceeds maximum allowed frame rate ({settings.SOURCE_VIDEO_MAX_FPS} fps).",
            },
        )

    # 2. Scene Detection
    scene_boundaries = detect_video_scenes(
        video_path=video_path,
        duration=metadata.duration,
        fps=metadata.fps,
    )
    if len(scene_boundaries) > settings.MAX_SCENE_COUNT_LIMIT:
        logger.warning(f"Detected scenes ({len(scene_boundaries)}) exceeds limit ({settings.MAX_SCENE_COUNT_LIMIT}); truncating.")
        scene_boundaries = scene_boundaries[:settings.MAX_SCENE_COUNT_LIMIT]
    logger.info(f"Detected {len(scene_boundaries)} scenes for video of duration {metadata.duration:.2f}s")

    # 3. Keyframe Extraction
    keyframes_dir = get_project_keyframes_dir(project_id)
    scene_results: List[SceneData] = []

    for seq, (start_t, end_t) in enumerate(scene_boundaries):
        dur = round(end_t - start_t, 3)
        # Midpoint of scene
        midpoint = round(start_t + (dur / 2.0), 3)

        # Generate unique stored filename for keyframe
        stored_kf_name = generate_stored_filename(".jpg")
        kf_output_path = keyframes_dir / stored_kf_name

        kf_data = extract_keyframe_image(
            video_path=video_path,
            timestamp=midpoint,
            output_image_path=kf_output_path,
            width=metadata.width,
            height=metadata.height,
        )
        kf_data.relative_path = f"projects/{project_id}/keyframes/{stored_kf_name}"

        scene_results.append(
            SceneData(
                sequence=seq,
                start_time=start_t,
                end_time=end_t,
                duration=dur,
                keyframe=kf_data,
            )
        )

    logger.info(f"Video analysis completed successfully with {len(scene_results)} scenes and keyframes.")
    return AnalysisResult(
        metadata=metadata,
        scenes=scene_results,
    )
