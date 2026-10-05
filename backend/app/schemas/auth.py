"""
3D Reel Studio — Authentication & User Schemas
Phase 16: Multi-User Authentication & Project Isolation
"""

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class UserRegister(BaseModel):
    """
    Payload for new user account registration.
    """
    email: str = Field(..., description="Unique email address for authentication")
    password: str = Field(..., min_length=8, max_length=128, description="Account password (min 8 chars)")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        trimmed = value.strip().lower()
        if not trimmed or not EMAIL_REGEX.match(trimmed):
            raise ValueError("A valid email address is required.")
        if len(trimmed) > 255:
            raise ValueError("Email address cannot exceed 255 characters.")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if len(value) > 128:
            raise ValueError("Password cannot exceed 128 characters.")
        return value


class UserLogin(BaseModel):
    """
    Payload for user login authentication.
    """
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        trimmed = value.strip().lower()
        if not trimmed:
            raise ValueError("Email is required.")
        return trimmed


class UserResponse(BaseModel):
    """
    Safe public user profile schema (never exposes password hashes).
    """
    id: str
    email: str
    is_active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AuthSuccessResponse(BaseModel):
    """
    Successful authentication response with signed access token.
    """
    success: bool = True
    token_type: str = "bearer"
    access_token: str
    expires_in: int
    user: UserResponse


class CurrentUserResponse(BaseModel):
    """
    Response schema for GET /api/v1/auth/me.
    """
    success: bool = True
    user: UserResponse


class AuthMessageResponse(BaseModel):
    """
    Generic success/status message response for auth actions (e.g. logout).
    """
    success: bool = True
    message: str
