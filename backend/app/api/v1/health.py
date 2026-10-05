from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.logging import logger
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.audio import resolve_ffmpeg_path
from app.services.storage import get_base_storage_dir

router = APIRouter(prefix="/health", tags=["Health & Diagnostics"])


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Health Check",
    description="Returns the operational status and version of the 3D Reel Studio API.",
)
@router.get(
    "/live",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Liveness Probe",
    description="Kubernetes / Docker container liveness probe verifying process is responsive.",
)
async def check_health() -> HealthResponse:
    """
    Health / Liveness check endpoint used by frontends, monitoring systems, and container orchestrators.
    """
    logger.debug("Health/Liveness check requested")
    return HealthResponse(
        success=True,
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Readiness Check",
    description="Indicates whether the application is ready to accept and process requests.",
)
async def check_readiness(db: Session = Depends(get_db)) -> ReadinessResponse:
    """
    Readiness probe endpoint verifying database connectivity, local storage accessibility,
    and FFmpeg binary resolution. Does not make external AI provider API calls.
    """
    logger.debug("Readiness check requested")
    subsystems = {
        "database": {"status": "ok"},
        "storage": {"status": "ok"},
        "ffmpeg": {"status": "ok"},
    }
    is_ready = True

    # 1. Database Connectivity Ping
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Readiness check failed on database: {e}")
        subsystems["database"] = {"status": "degraded", "error": "Database ping failed"}
        is_ready = False

    # 2. Storage Directory Check
    try:
        storage_dir = get_base_storage_dir()
        if not storage_dir.exists() or not storage_dir.is_dir():
            subsystems["storage"] = {"status": "degraded", "error": "Storage directory missing"}
            is_ready = False
    except Exception as e:
        logger.error(f"Readiness check failed on storage: {e}")
        subsystems["storage"] = {"status": "degraded", "error": "Storage check failed"}
        is_ready = False

    # 3. FFmpeg Binary Resolution
    ffmpeg_bin = resolve_ffmpeg_path()
    if not ffmpeg_bin:
        subsystems["ffmpeg"] = {"status": "degraded", "warning": "FFmpeg binary not resolved"}
        # We don't mark completely unready if mock mode can operate, but mark status degraded
    else:
        subsystems["ffmpeg"]["path"] = ffmpeg_bin

    overall_status = "ready" if is_ready else "degraded"

    return ReadinessResponse(
        success=is_ready,
        status=overall_status,
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        subsystems=subsystems,
    )
