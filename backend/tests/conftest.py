"""
3D Reel Studio — Test Configuration & Fixtures
Phase 2 & Phase 16: FastAPI Backend Foundation & Multi-User Authentication
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal, init_db
from app.main import app
from app.models.user import User


def get_or_create_test_user(
    db: Session,
    user_id: str = "USR-DEFAULT-DEV",
    email: str = "dev@3dreelstudio.local",
) -> User:
    """
    Ensures deterministic test user exists in the database.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            id=user_id,
            email=email,
            password_hash=hash_password("DevStudio2026!"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_test_auth_headers(
    user_id: str = "USR-DEFAULT-DEV",
    email: str = "dev@3dreelstudio.local",
) -> dict:
    """
    Generates Bearer Authorization headers for a specific user ID/email.
    """
    token = create_access_token(user_id=user_id, email=email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """
    Initializes database schema and default test users before running tests.
    """
    init_db()
    db = SessionLocal()
    try:
        get_or_create_test_user(db, "USR-DEFAULT-DEV", "dev@3dreelstudio.local")
        get_or_create_test_user(db, "USR-TEST-A", "user_a@test.local")
        get_or_create_test_user(db, "USR-TEST-B", "user_b@test.local")
    finally:
        db.close()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """
    Synchronous TestClient fixture with authenticated default test user.
    """
    headers = get_test_auth_headers("USR-DEFAULT-DEV", "dev@3dreelstudio.local")
    with TestClient(app, headers=headers) as test_client:
        yield test_client


@pytest.fixture
def unauthenticated_client() -> TestClient:
    """
    TestClient fixture with NO authentication headers.
    """
    with TestClient(app) as test_client:
        yield test_client
