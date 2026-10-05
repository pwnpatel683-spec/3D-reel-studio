"""
3D Reel Studio — API Dependency System
Phase 16: Multi-User Authentication & Ownership Isolation
"""

from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User


def extract_token_from_request(request: Request) -> Optional[str]:
    """
    Extracts authentication token from Authorization Bearer header,
    X-Auth-Token header, or HTTP cookie.
    """
    # 1. Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        elif len(parts) == 1:
            return parts[0]

    # 2. X-Auth-Token header
    x_token = request.headers.get("X-Auth-Token")
    if x_token:
        return x_token.strip()

    # 3. Cookie access_token
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token.strip()

    return None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Strict authentication dependency. Validates signed JWT token,
    authenticates active user identity, and prevents unauthenticated access.
    """
    token = extract_token_from_request(request)
    if not token:
        logger.debug(f"Unauthenticated request to protected endpoint: {request.method} {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Authentication required. Please provide a valid Bearer token.",
            },
        )

    payload = decode_access_token(token)
    if not payload:
        logger.warning(f"Rejected invalid or expired token on {request.method} {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Invalid, expired, or tampered authentication token. Please log in again.",
            },
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        logger.warning(f"Authentication token references non-existent or deactivated user ID '{user_id}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "USER_NOT_FOUND",
                "message": "User account associated with this token does not exist or has been disabled.",
            },
        )

    return user


async def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Optional authentication dependency. Returns User if a valid token is present,
    or None if request is unauthenticated.
    """
    token = extract_token_from_request(request)
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
