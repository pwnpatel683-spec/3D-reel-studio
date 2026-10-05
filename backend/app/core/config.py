"""
3D Reel Studio — Application Configuration
Phase 2, 3 & 4: FastAPI Backend, Persistence & Media Storage
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized application configuration loaded from environment variables
    with fallback defaults.
    """
    # Application Info
    APP_NAME: str = "3D Reel Studio API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "Backend API for the 3D Reel Studio AI video transformation platform."
    ENVIRONMENT: str = "development"
    APP_ENV: Union[str, None] = None
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    DOCS_ENABLED: bool = True

    # Server Networking
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    API_PREFIX: str = "/api/v1"

    # Database Configuration (SQLite / PostgreSQL)
    DATABASE_URL: str = "sqlite:///data/studio.db"
    DATA_DIR: str = "data"

    # Media Storage Configuration & Safety Bounds
    STORAGE_DIR: str = "storage"
    MEDIA_STORAGE_ROOT: Union[str, None] = None
    TEMP_STORAGE_ROOT: str = "storage/temp"
    SOURCE_VIDEO_MAX_SIZE_MB: int = 500
    MAX_UPLOAD_SIZE: Union[int, None] = None
    FACE_REFERENCE_MAX_SIZE_MB: int = 25
    SOURCE_VIDEO_MAX_DURATION_SECONDS: float = 600.0  # Max 10 minutes video
    MAX_VIDEO_DURATION: Union[float, None] = None
    SOURCE_VIDEO_MAX_WIDTH: int = 3840  # Max 4K resolution
    SOURCE_VIDEO_MAX_HEIGHT: int = 3840
    SOURCE_VIDEO_MAX_FPS: float = 120.0
    MAX_SCENE_COUNT_LIMIT: int = 100

    # Pipeline Operation Timeouts & Concurrency (Seconds)
    PROCESSING_TIMEOUT: Union[int, None] = None
    FFMPEG_TIMEOUT_SECONDS: int = 180
    TRANSCRIPTION_TIMEOUT_SECONDS: int = 60
    COMIC_GENERATION_TIMEOUT_SECONDS: int = 60
    SEGMENTATION_TIMEOUT_SECONDS: int = 60
    RENDER_TIMEOUT_SECONDS: int = 300
    MAX_CONCURRENT_RENDERS: int = 2
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60

    # FFmpeg Media Engine Configuration
    FFMPEG_PATH: str = "ffmpeg"

    # OpenAI AI Audio Transcription Configuration
    OPENAI_API_KEY: Union[str, None] = None
    OPENAI_TRANSCRIPTION_MODEL: str = "whisper-1"

    # 3D Comic Generation Configuration (Phase 9)
    COMIC_GENERATION_PROVIDER: str = "openai"  # "openai" or "mock"
    COMIC_GENERATION_MODEL: str = "dall-e-3"
    COMIC_GENERATION_API_KEY: Union[str, None] = None

    # Foreground Segmentation & Background Layering (Phase 11)
    SEGMENTATION_PROVIDER: str = "opencv_guided"  # "opencv_guided" or "mock"
    SEGMENTATION_MODEL: str = "grabcut_pose_prior"
    SEGMENTATION_DEFAULT_BG_MODE: str = "ORIGINAL"  # ORIGINAL, SOFT_BLUR, DEPTH_STYLE, COMIC_STYLE

    # Frontend & CORS Configuration
    FRONTEND_URL: str = "http://localhost:8080"
    CORS_ORIGINS: Union[List[str], str] = ["*"]
    CORS_ALLOWED_ORIGINS: Union[List[str], str, None] = None

    # Authentication & Project Ownership Configuration (Phase 16)
    AUTH_SECRET: str = "3d-reel-studio-super-secret-key-change-in-prod"
    AUTH_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10

    @field_validator("CORS_ORIGINS", "CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[List[str], str, None]) -> List[str]:
        """
        Parses CORS origins from JSON arrays, comma-separated strings, or plain lists.
        """
        if value is None:
            return ["*"]
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            if "," in value:
                return [origin.strip() for origin in value.split(",") if origin.strip()]
            return [value] if value else ["*"]
        return ["*"]

    def model_post_init(self, __context) -> None:
        """
        Harmonizes aliases and environment variables for seamless deployment.
        """
        if self.APP_ENV:
            self.ENVIRONMENT = self.APP_ENV
        if self.ENVIRONMENT == "production":
            self.DEBUG = False
        if self.MEDIA_STORAGE_ROOT:
            self.STORAGE_DIR = self.MEDIA_STORAGE_ROOT
        if self.CORS_ALLOWED_ORIGINS and self.CORS_ALLOWED_ORIGINS != ["*"]:
            self.CORS_ORIGINS = self.CORS_ALLOWED_ORIGINS
        if self.MAX_UPLOAD_SIZE:
            # If specified in bytes, convert to MB
            self.SOURCE_VIDEO_MAX_SIZE_MB = max(1, self.MAX_UPLOAD_SIZE // (1024 * 1024))
        if self.MAX_VIDEO_DURATION:
            self.SOURCE_VIDEO_MAX_DURATION_SECONDS = float(self.MAX_VIDEO_DURATION)
        if self.PROCESSING_TIMEOUT:
            self.RENDER_TIMEOUT_SECONDS = int(self.PROCESSING_TIMEOUT)
            self.FFMPEG_TIMEOUT_SECONDS = int(self.PROCESSING_TIMEOUT)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached instance of application settings.
    """
    return Settings()


settings = get_settings()
