"""
3D Reel Studio — Audio Extraction Service
Phase 5: FFmpeg Audio Extraction Engine
"""

import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Tuple
from fastapi import HTTPException, status
from app.core.config import settings
from app.core.logging import logger
from app.services.storage import get_base_storage_dir


def get_project_audio_dir(project_id: str) -> Path:
    """
    Returns the isolated storage directory for a project's extracted audio.
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
        logger.warning(f"Path traversal attempt rejected for audio storage: '{project_id}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project identifier (path traversal prohibited).",
        )

    base_storage = get_base_storage_dir()
    audio_dir = base_storage / "projects" / clean_id / "audio"

    try:
        resolved_audio = audio_dir.resolve()
        resolved_base = base_storage.resolve()
        if not str(resolved_audio).startswith(str(resolved_base)):
            raise ValueError("Resolved audio path falls outside base storage directory.")
    except Exception as e:
        logger.error(f"Security error validating audio directory path: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project path identifiers.",
        )

    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def resolve_ffmpeg_path() -> Optional[str]:
    """
    Resolves the system or configured FFmpeg executable path.
    Checks config, system PATH, and standard installation locations.
    """
    configured = settings.FFMPEG_PATH.strip()

    # 1. If configured path exists as a direct file
    if configured and Path(configured).is_file():
        return configured

    # 2. Check system PATH via shutil.which
    which_path = shutil.which(configured) or shutil.which("ffmpeg")
    if which_path:
        return which_path

    # 3. Check Windows WinGet / standard fallback directories
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            for ffmpeg_exe in winget_pkgs.glob("**/ffmpeg.exe"):
                if ffmpeg_exe.is_file():
                    return str(ffmpeg_exe)

    program_files = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
    for pf in program_files:
        if pf:
            for candidate in [
                Path(pf) / "ffmpeg" / "bin" / "ffmpeg.exe",
                Path(pf) / "FFmpeg" / "bin" / "ffmpeg.exe",
            ]:
                if candidate.is_file():
                    return str(candidate)

    return None


def probe_video_has_audio(video_path: Path, ffmpeg_bin: str) -> bool:
    """
    Inspects source video streams using FFmpeg without transcoding to determine if an audio stream exists.
    """
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
        stderr_output = proc.stderr.lower()

        # Check for presence of audio stream
        if "audio:" in stderr_output or "stream #" in stderr_output and "audio" in stderr_output:
            return True
        return False
    except Exception as e:
        logger.warning(f"Audio stream probe encountered note: {e}")
        return True  # Fallback to extraction execution if probe fails


def extract_audio_from_video(
    source_video_path: Path,
    output_audio_path: Path,
) -> Tuple[int, str]:
    """
    Transcodes and extracts audio track from source video to MP3 format using FFmpeg.
    Enforces safe subprocess execution, audio stream validation, and SHA-256 calculation.
    Returns (file_size_bytes, sha256_hex).
    """
    if not source_video_path.exists() or not source_video_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source video file does not exist on storage.",
        )

    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        logger.error("FFmpeg executable not found on system.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FFmpeg executable is not available on the system. Please configure FFMPEG_PATH or install FFmpeg.",
        )

    # 1. Probe for audio stream existence
    has_audio = probe_video_has_audio(source_video_path, ffmpeg_bin)
    if not has_audio:
        logger.warning(f"Extraction rejected: '{source_video_path.name}' has no audio stream.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "NO_AUDIO_STREAM",
                "message": "The source video does not contain an audio stream.",
            },
        )

    # 2. Prepare destination parent directory
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)

    # 3. Construct safe FFmpeg argument array (NO shell=True)
    cmd = [
        ffmpeg_bin,
        "-y",                   # Overwrite output file without prompting
        "-i", str(source_video_path),  # Input file
        "-vn",                  # Disable video recording
        "-acodec", "libmp3lame", # MP3 codec
        "-ar", "44100",         # 44.1 kHz sample rate
        "-ac", "2",             # Stereo 2 channels
        "-b:a", "192k",         # 192k bitrate
        str(output_audio_path), # Output MP3 destination
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
        )

        if proc.returncode != 0:
            stderr_lower = proc.stderr.lower()
            logger.error(f"FFmpeg transcoding failed (exit code {proc.returncode}): {proc.stderr}")

            if output_audio_path.exists():
                output_audio_path.unlink(missing_ok=True)

            if "does not contain any stream" in stderr_lower or "matches no streams" in stderr_lower or "no audio" in stderr_lower:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "NO_AUDIO_STREAM",
                        "message": "The source video does not contain an audio stream.",
                    },
                )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio extraction failed during media transcoding.",
            )

        if not output_audio_path.exists() or output_audio_path.stat().st_size == 0:
            if output_audio_path.exists():
                output_audio_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "NO_AUDIO_STREAM",
                    "message": "The source video does not contain an audio stream.",
                },
            )

        # 4. Compute file size and SHA-256 checksum
        file_size = output_audio_path.stat().st_size
        sha256 = hashlib.sha256()
        with open(output_audio_path, "rb") as f:
            while chunk := f.read(64 * 1024):
                sha256.update(chunk)
        sha256_hex = sha256.hexdigest()

        return file_size, sha256_hex

    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        if output_audio_path.exists():
            output_audio_path.unlink(missing_ok=True)
        logger.error(f"FFmpeg process timed out extracting audio from {source_video_path.name}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audio extraction timed out.",
        )
    except Exception as e:
        if output_audio_path.exists():
            output_audio_path.unlink(missing_ok=True)
        logger.error(f"Unexpected error during FFmpeg execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audio extraction failed due to an internal server error.",
        )
