"""
3D Reel Studio — Standardized API Response Schemas
Phase 2: FastAPI Backend Foundation
"""

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class APIErrorDetail(BaseModel):
    """
    Standard error description payload.
    """
    code: str = Field(..., description="Machine-readable uppercase error code")
    message: str = Field(..., description="Human-readable error explanation")
    details: Optional[Any] = Field(None, description="Optional extra diagnostic details or field errors")


class APIErrorResponse(BaseModel):
    """
    Standard envelope for all error responses across the API.
    """
    success: bool = Field(False, description="Always False for error responses")
    error: APIErrorDetail


class APIResponse(BaseModel, Generic[DataT]):
    """
    Standard envelope for successful API responses.
    """
    success: bool = Field(True, description="Always True for successful responses")
    data: Optional[DataT] = Field(None, description="Response payload data")


class RootResponse(BaseModel):
    """
    Root endpoint status schema.
    """
    success: bool = Field(True, description="Service operational status")
    message: str = Field(..., description="Welcome or status message")
    docs: str = Field("/docs", description="Interactive API documentation path")
