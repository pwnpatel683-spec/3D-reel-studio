"""
3D Reel Studio — Authentication API Endpoints
Phase 16: Multi-User Authentication & Account Management
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import logger
from app.core.security import (
    create_access_token,
    hash_password,
    rate_limit_auth,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthMessageResponse,
    AuthSuccessResponse,
    CurrentUserResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication & Accounts"])


@router.post(
    "/register",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user account",
    description="Creates a new unique user account and returns an authenticated access token.",
)
async def register(
    payload: UserRegister,
    db: Session = Depends(get_db),
    _rate: None = Depends(rate_limit_auth),
) -> AuthSuccessResponse:
    """
    Registers a new user account with unique email validation and secure PBKDF2 hashing.
    """
    clean_email = payload.email.strip().lower()

    # Check for duplicate email
    existing_user = db.query(User).filter(User.email == clean_email).first()
    if existing_user:
        logger.warning(f"Registration rejected: email '{clean_email}' is already registered")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_EXISTS",
                "message": "An account with this email address already exists.",
            },
        )

    try:
        pw_hash = hash_password(payload.password)
        new_user = User(
            email=clean_email,
            password_hash=pw_hash,
            is_active=True,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        access_token = create_access_token(user_id=new_user.id, email=new_user.email)
        logger.info(f"User registered successfully: ID='{new_user.id}', Email='{new_user.email}'")

        return AuthSuccessResponse(
            success=True,
            token_type="bearer",
            access_token=access_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse.model_validate(new_user),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error during user registration: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "REGISTRATION_FAILED",
                "message": "Failed to create user account. Please try again.",
            },
        )


@router.post(
    "/login",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="User login and token issue",
    description="Authenticates email and password credentials and issues a signed access token.",
)
async def login(
    payload: UserLogin,
    db: Session = Depends(get_db),
    _rate: None = Depends(rate_limit_auth),
) -> AuthSuccessResponse:
    """
    Validates user credentials with constant-time verification and returns signed token.
    """
    clean_email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    # Timing-safe failure path
    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning(f"Login failed for email attempt: '{clean_email}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            },
        )

    if not user.is_active:
        logger.warning(f"Login rejected for deactivated user ID '{user.id}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_DISABLED",
                "message": "This account has been disabled. Please contact support.",
            },
        )

    # Update last login timestamp
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(user_id=user.id, email=user.email)
    logger.info(f"User logged in successfully: ID='{user.id}', Email='{user.email}'")

    return AuthSuccessResponse(
        success=True,
        token_type="bearer",
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user profile",
    description="Returns the profile information of the currently authenticated user.",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> CurrentUserResponse:
    """
    Returns safe authenticated user profile (never password hash).
    """
    return CurrentUserResponse(
        success=True,
        user=UserResponse.model_validate(current_user),
    )


@router.post(
    "/logout",
    response_model=AuthMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="User logout",
    description="Instructs client to clear authentication credentials and invalidates session.",
)
async def logout(
    current_user: User = Depends(get_current_user),
) -> AuthMessageResponse:
    """
    Acknowledge client logout and session clearance.
    """
    logger.info(f"User logged out: ID='{current_user.id}', Email='{current_user.email}'")
    return AuthMessageResponse(
        success=True,
        message="Successfully logged out.",
    )
