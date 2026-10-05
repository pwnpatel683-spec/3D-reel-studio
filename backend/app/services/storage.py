"""
3D Reel Studio — Local Media Storage Service
Phase 4: Multipart Media Upload & Secure Storage
"""

import hashlib
import uuid
from pathlib import Path
from typing import Optional, Set, Tuple
from fastapi import HTTPException, UploadFile, status
from app.core.config import settings
from app.core.logging import logger

# Supported video formats and MIME types
ALLOWED_VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mov", ".webm"}
ALLOWED_VIDEO_MIMES: Set[str] = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
    "video/x-msvideo",
    "application/octet-stream",
}

# Supported face reference image formats and MIME types
ALLOWED_IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png"}
ALLOWED_IMAGE_MIMES: Set[str] = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/pjpeg",
    "application/octet-stream",
}

ALLOWED_MEDIA_TYPES: Set[str] = {"source_video", "face_reference"}


def get_base_storage_dir() -> Path:
    """Returns the absolute base storage directory."""
    backend_root = Path(__file__).resolve().parent.parent.parent
    storage_path = backend_root / settings.STORAGE_DIR
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def get_project_storage_dir(project_id: str, media_type: str) -> Path:
    """
    Returns the secure, isolated directory for a project's media type.
    Enforces strict path traversal prevention.
    """
    clean_id = project_id.strip()

    # Reject path traversal tokens
    if (
        not clean_id
        or ".." in clean_id
        or "/" in clean_id
        or "\\" in clean_id
        or clean_id.startswith(".")
    ):
        logger.warning(f"Path traversal attempt rejected for project_id: '{project_id}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project identifier (path traversal prohibited).",
        )

    sub_dir_map = {
        "source_video": "source",
        "face_reference": "face-reference",
        "extracted_audio": "audio",
        "keyframe_image": "keyframes",
        "comic_frame": "comic-frames",
        "consistent_comic_frame": "consistent-frames",
        "segmentation_mask": "segmentation/masks",
        "segmentation_foreground": "segmentation/foregrounds",
        "segmentation_background": "segmentation/backgrounds",
        "segmentation_composite": "segmentation/composites",
        "segmentation": "segmentation",
        "lyrics_preview": "lyrics/previews",
        "lyrics": "lyrics",
        "final_reel": "final",
        "final_video": "final",
        "renders": "renders",
    }
    sub_dir_name = sub_dir_map.get(media_type, media_type)
    base_storage = get_base_storage_dir()
    project_dir = base_storage / "projects" / clean_id / sub_dir_name

    # Canonical path boundary validation
    try:
        resolved_proj = project_dir.resolve()
        resolved_base = base_storage.resolve()
        if not str(resolved_proj).startswith(str(resolved_base)):
            raise ValueError("Resolved storage path falls outside base storage directory.")
    except Exception as e:
        logger.error(f"Security error validating project storage path: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project path identifiers.",
        )

    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def sanitize_extension(filename: str) -> str:
    """Extracts and lowercases the file extension."""
    if not filename:
        return ""
    return Path(filename).suffix.lower()


def validate_media_upload(
    filename: Optional[str],
    content_type: Optional[str],
    media_type: str,
) -> Tuple[str, int]:
    """
    Validates media_type, file extension, MIME type, and returns (extension, max_bytes_limit).
    """
    # 1. Validate media_type
    clean_media_type = (media_type or "").strip().lower()
    if clean_media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid media_type '{media_type}'. Allowed: 'source_video', 'face_reference'.",
        )

    # 2. Validate filename and extension
    if not filename or not filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided in upload payload.",
        )

    ext = sanitize_extension(filename)
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has no extension. Please upload a valid media file.",
        )

    clean_content_type = (content_type or "").strip().lower()

    # 3. Media-specific validation
    if clean_media_type == "source_video":
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            allowed_str = ", ".join(sorted(ALLOWED_VIDEO_EXTENSIONS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}' for source video. Allowed: {allowed_str}.",
            )
        if clean_content_type and clean_content_type not in ALLOWED_VIDEO_MIMES and not clean_content_type.startswith("video/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid MIME type '{content_type}' for source video.",
            )
        max_bytes = settings.SOURCE_VIDEO_MAX_SIZE_MB * 1024 * 1024
    else:  # face_reference
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            allowed_str = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}' for face reference. Allowed: {allowed_str}.",
            )
        if clean_content_type and clean_content_type not in ALLOWED_IMAGE_MIMES and not clean_content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid MIME type '{content_type}' for face reference.",
            )
        max_bytes = settings.FACE_REFERENCE_MAX_SIZE_MB * 1024 * 1024

    return ext, max_bytes


def generate_stored_filename(extension: str) -> str:
    """
    Generates a unique, server-side filename (e.g. 'c4a8f9d3b2e1c4a5b6d7e8f9a0b1c2d3.mp4').
    The client never controls the stored filename.
    """
    unique_id = uuid.uuid4().hex
    return f"{unique_id}{extension}"


async def save_upload_file_chunked(
    upload_file: UploadFile,
    target_path: Path,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> Tuple[int, str]:
    """
    Streams the upload file to disk in chunks, enforcing max file size and
    calculating SHA-256 hash simultaneously without loading the entire file into RAM.
    Returns (total_bytes_written, sha256_hex).
    """
    total_written = 0
    sha256 = hashlib.sha256()

    try:
        with open(target_path, "wb") as buffer:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > max_bytes:
                    max_mb = max_bytes // (1024 * 1024)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {max_mb} MB.",
                    )
                sha256.update(chunk)
                buffer.write(chunk)

        if total_written == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )

        return total_written, sha256.hexdigest()

    except Exception:
        # Cleanup partially written or empty file if failure occurs
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass
        raise


def delete_physical_file(file_path_str: str) -> bool:
    """
    Safely deletes a physical media file, ensuring no escape from storage root.
    """
    if not file_path_str:
        return False

    base_storage = get_base_storage_dir()
    target_path = Path(file_path_str)

    if not target_path.is_absolute():
        target_path = base_storage / file_path_str

    try:
        resolved = target_path.resolve()
        if not str(resolved).startswith(str(base_storage.resolve())):
            logger.warning(f"Path traversal attempt prevented on delete: '{file_path_str}'")
            return False

        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            logger.info(f"Deleted physical media file: {resolved}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting physical file '{file_path_str}': {e}")
        return False


# -----------------------------------------------------------------------------
# Storage Architecture Abstraction (Phase 15)
# -----------------------------------------------------------------------------

from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Any


class MediaStorage(ABC):
    """
    Abstract storage backend interface for 3D Reel Studio media files.
    Allows local filesystem storage to be swapped with S3 / GCS / Azure Blob storage without changing pipeline code.
    """

    @abstractmethod
    def save(self, project_id: str, media_type: str, filename: str, data: bytes) -> Tuple[Path, int, str]:
        """Saves raw bytes into storage and returns (absolute_path, file_size, sha256_hex)."""
        pass

    @abstractmethod
    def open(self, file_path_str: str) -> BinaryIO:
        """Opens and returns a binary file stream for reading."""
        pass

    @abstractmethod
    def exists(self, file_path_str: str) -> bool:
        """Checks if a file exists within storage."""
        pass

    @abstractmethod
    def delete(self, file_path_str: str) -> bool:
        """Deletes a file safely from storage."""
        pass

    @abstractmethod
    def get_metadata(self, file_path_str: str) -> Dict[str, Any]:
        """Returns file metadata: size, sha256, exists, mime."""
        pass

    @abstractmethod
    def generate_download_reference(self, project_id: str, media_id: str) -> str:
        """Generates relative/presigned download reference URL."""
        pass


class LocalMediaStorage(MediaStorage):
    """
    Production-ready local filesystem storage backend implementation.
    Enforces project-level isolation, strict path traversal defenses, and chunked I/O.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self._root_dir = root_dir or get_base_storage_dir()

    def get_base_dir(self) -> Path:
        return self._root_dir

    def save(self, project_id: str, media_type: str, filename: str, data: bytes) -> Tuple[Path, int, str]:
        target_dir = get_project_storage_dir(project_id, media_type)
        ext = sanitize_extension(filename) or ".bin"
        stored_name = generate_stored_filename(ext)
        target_path = target_dir / stored_name
        target_path.write_bytes(data)
        file_size = len(data)
        sha256_hex = hashlib.sha256(data).hexdigest()
        return target_path, file_size, sha256_hex

    def open(self, file_path_str: str) -> BinaryIO:
        base_storage = get_base_storage_dir()
        p = Path(file_path_str)
        if not p.is_absolute():
            p = base_storage / file_path_str
        resolved = p.resolve()
        if not str(resolved).startswith(str(base_storage.resolve())):
            raise ValueError("Path traversal violation attempting to open file.")
        if not resolved.is_file():
            raise FileNotFoundError(f"Storage file not found: {file_path_str}")
        return open(resolved, "rb")

    def exists(self, file_path_str: str) -> bool:
        if not file_path_str:
            return False
        base_storage = get_base_storage_dir()
        p = Path(file_path_str)
        if not p.is_absolute():
            p = base_storage / file_path_str
        try:
            resolved = p.resolve()
            return str(resolved).startswith(str(base_storage.resolve())) and resolved.is_file()
        except Exception:
            return False

    def delete(self, file_path_str: str) -> bool:
        return delete_physical_file(file_path_str)

    def get_metadata(self, file_path_str: str) -> Dict[str, Any]:
        if not self.exists(file_path_str):
            return {"exists": False, "size": 0, "sha256": None}
        base_storage = get_base_storage_dir()
        p = Path(file_path_str)
        if not p.is_absolute():
            p = base_storage / file_path_str
        resolved = p.resolve()
        data = resolved.read_bytes()
        return {
            "exists": True,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "path": str(resolved),
        }

    def generate_download_reference(self, project_id: str, media_id: str) -> str:
        return f"{settings.API_PREFIX}/projects/{project_id}/media/{media_id}/download"


# Singleton default storage instance
default_storage: MediaStorage = LocalMediaStorage()
