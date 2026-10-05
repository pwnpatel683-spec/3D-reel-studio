from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """
    Health check response model.
    """
    success: bool = Field(True, description="Indicates server status check was successful")
    status: str = Field("healthy", description="Current health status (e.g. healthy, degraded)")
    service: str = Field(..., description="Service identifier name")
    version: str = Field(..., description="Semantic API version string")


class ReadinessResponse(BaseModel):
    """
    Readiness probe response model for load balancers and frontends.
    """
    success: bool = Field(True, description="Indicates server readiness check was successful")
    status: str = Field("ready", description="Current readiness status (e.g. ready, initializing, degraded)")
    service: str = Field(..., description="Service identifier name")
    version: str = Field(..., description="Semantic API version string")
    subsystems: Optional[Dict[str, Any]] = Field(None, description="Diagnostic state of subsystems (database, storage, ffmpeg)")

