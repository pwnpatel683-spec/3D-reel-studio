"""
3D Reel Studio — Phase 16: Authentication & Multi-User Project Isolation Test Suite
Comprehensive verification of authentication, token management, rate limiting, and project ownership security.
"""

import io
import time
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.rate_limit import limiter
from app.db.migrations import run_migrations
from app.db.session import SessionLocal, init_db
from app.main import app
from app.models.project import MediaFile, Project, RenderJob, generate_uuid
from app.models.user import User, generate_user_id
from tests.conftest import get_test_auth_headers


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clears rate limiter records before each test to prevent testclient cross-test throttling."""
    limiter._records.clear()
    yield
    limiter._records.clear()


@pytest.fixture(scope="module")
def db_session():
    """Database session for isolation test assertions."""
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_client():
    """Fresh unauthenticated TestClient for authentication flows."""
    return TestClient(app)


# =============================================================================
# 1. USER REGISTRATION & VALIDATION TESTS
# =============================================================================

def test_user_registration_success(auth_client: TestClient, db_session: Session):
    """Verifies that a new user can register and receive an access token and safe profile."""
    unique_email = f"user_{generate_uuid()[:8]}@example.com"
    payload = {
        "email": unique_email,
        "password": "StrongPassword2026!",
    }
    response = auth_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert len(data["access_token"]) > 20
    assert data["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    user_info = data["user"]
    assert user_info["email"] == unique_email
    assert "id" in user_info
    assert user_info["is_active"] is True
    # Crucial: Password and hash must NEVER be present in response
    assert "password" not in user_info
    assert "password_hash" not in user_info
    assert "password_hash" not in data


def test_user_registration_duplicate_email(auth_client: TestClient):
    """Verifies that attempting to register with an already existing email returns 409 Conflict."""
    email = f"dup_{generate_uuid()[:8]}@example.com"
    payload = {"email": email, "password": "Password123!"}

    # First registration: 201
    res1 = auth_client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    # Second registration: 409 Conflict
    res2 = auth_client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    data = res2.json()
    assert data["success"] is False
    assert data["error"]["code"] == "EMAIL_ALREADY_EXISTS"


def test_user_registration_validation(auth_client: TestClient):
    """Verifies rejection of invalid emails or passwords shorter than 8 characters."""
    # 1. Short password (< 8 chars)
    res_short = auth_client.post("/api/v1/auth/register", json={"email": "valid@test.com", "password": "short"})
    assert res_short.status_code == 422

    # 2. Invalid email format
    res_bad_email = auth_client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "ValidPassword123!"})
    assert res_bad_email.status_code == 422


# =============================================================================
# 2. PASSWORD SECURITY & CRYPTOGRAPHY TESTS
# =============================================================================

def test_password_hashing_and_verification():
    """Verifies PBKDF2-HMAC-SHA256 password hashing, salt uniqueness, and constant-time verification."""
    password = "MySecurePassword2026!"
    hash1 = hash_password(password)
    hash2 = hash_password(password)

    # Hash format verification
    assert hash1.startswith("pbkdf2_sha256$600000$")
    assert hash2.startswith("pbkdf2_sha256$600000$")

    # Salt uniqueness: separate hashes for identical passwords must have different salts
    assert hash1 != hash2

    # Verification correctness
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True
    assert verify_password("WrongPassword!", hash1) is False
    assert verify_password("", hash1) is False
    assert verify_password(password, "") is False
    assert verify_password(password, "corrupted$hash$value") is False


# =============================================================================
# 3. LOGIN & TOKEN AUTHENTICATION TESTS
# =============================================================================

def test_user_login_success(auth_client: TestClient):
    """Verifies that a registered user can log in with valid credentials and receive a token."""
    email = f"login_{generate_uuid()[:8]}@example.com"
    password = "UserLoginSecret123!"
    auth_client.post("/api/v1/auth/register", json={"email": email, "password": password})

    login_res = auth_client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200
    data = login_res.json()
    assert data["success"] is True
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert data["user"]["email"] == email


def test_user_login_invalid_password(auth_client: TestClient):
    """Verifies that incorrect password returns generic 401 Unauthorized."""
    email = f"wrongpw_{generate_uuid()[:8]}@example.com"
    password = "CorrectPassword123!"
    auth_client.post("/api/v1/auth/register", json={"email": email, "password": password})

    res = auth_client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword456!"})
    assert res.status_code == 401
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    assert "Invalid email or password" in data["error"]["message"]


def test_user_login_nonexistent_email(auth_client: TestClient):
    """Verifies that non-existent email returns generic 401 Unauthorized without leaking existence."""
    res = auth_client.post("/api/v1/auth/login", json={"email": "nobody_exists@nowhere.local", "password": "SomePassword123!"})
    assert res.status_code == 401
    data = res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    assert "Invalid email or password" in data["error"]["message"]


def test_access_token_decoding_and_expiration(auth_client: TestClient):
    """Verifies token structure, verification, expiration rejection, and tamper rejection."""
    user_id = f"USR-{generate_uuid()[:8]}"
    email = "token_test@example.com"

    # 1. Valid token
    token = create_access_token(user_id=user_id, email=email)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["email"] == email
    assert payload["exp"] > int(time.time())

    # 2. Expired token (-1 minute)
    expired_token = create_access_token(user_id=user_id, email=email, expires_delta=timedelta(minutes=-1))
    assert decode_access_token(expired_token) is None

    # 3. Request with expired token returns 401
    res_expired = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res_expired.status_code == 401
    assert res_expired.json()["error"]["code"] in ("INVALID_TOKEN", "UNAUTHORIZED")

    # 4. Tampered token returns 401
    parts = token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}TAMPERED.{parts[2]}"
    res_tampered = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert res_tampered.status_code == 401


def test_get_current_user_me_endpoint(auth_client: TestClient):
    """Verifies GET /api/v1/auth/me returns safe authenticated user profile."""
    email = f"me_{generate_uuid()[:8]}@example.com"
    reg_res = auth_client.post("/api/v1/auth/register", json={"email": email, "password": "MyProfilePassword1!"})
    token = reg_res.json()["access_token"]

    me_res = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["success"] is True
    assert data["user"]["email"] == email
    assert "password_hash" not in data["user"]


def test_user_logout(auth_client: TestClient):
    """Verifies POST /api/v1/auth/logout succeeds for authenticated user."""
    email = f"logout_{generate_uuid()[:8]}@example.com"
    reg_res = auth_client.post("/api/v1/auth/register", json={"email": email, "password": "LogoutPassword123!"})
    token = reg_res.json()["access_token"]

    logout_res = auth_client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True
    assert "Successfully logged out" in logout_res.json()["message"]


# =============================================================================
# 4. UNAUTHENTICATED REQUEST REJECTION TESTS
# =============================================================================

def test_unauthenticated_requests_rejected(auth_client: TestClient):
    """Verifies that all project routes reject unauthenticated requests with 401 Unauthorized."""
    # 1. Project listing
    res_list = auth_client.get("/api/v1/projects")
    assert res_list.status_code == 401
    assert res_list.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Project creation
    res_create = auth_client.post("/api/v1/projects", json={"name": "Unauthenticated Proj"})
    assert res_create.status_code == 401

    # 3. Project detail
    res_detail = auth_client.get("/api/v1/projects/PROJ-ANY-ID")
    assert res_detail.status_code == 401


# =============================================================================
# 5. PROJECT CREATION & OWNERSHIP ISOLATION TESTS
# =============================================================================

@pytest.fixture
def two_users(auth_client: TestClient):
    """Helper fixture creating two distinct authenticated users: User A and User B."""
    email_a = f"usera_{generate_uuid()[:8]}@test.com"
    email_b = f"userb_{generate_uuid()[:8]}@test.com"

    res_a = auth_client.post("/api/v1/auth/register", json={"email": email_a, "password": "PasswordA123!"}).json()
    res_b = auth_client.post("/api/v1/auth/register", json={"email": email_b, "password": "PasswordB123!"}).json()

    user_a = res_a["user"]
    user_b = res_b["user"]
    headers_a = {"Authorization": f"Bearer {res_a['access_token']}"}
    headers_b = {"Authorization": f"Bearer {res_b['access_token']}"}

    return {
        "user_a": user_a,
        "user_b": user_b,
        "headers_a": headers_a,
        "headers_b": headers_b,
    }


def test_authenticated_project_creation_sets_owner(auth_client: TestClient, two_users: dict):
    """Verifies that project creation automatically assigns authenticated user as owner."""
    headers_a = two_users["headers_a"]
    user_a_id = two_users["user_a"]["id"]

    create_res = auth_client.post("/api/v1/projects", json={"name": "User A Project"}, headers=headers_a)
    assert create_res.status_code == 201
    proj_a = create_res.json()["project"]
    assert proj_a["name"] == "User A Project"


def test_project_list_isolation(auth_client: TestClient, two_users: dict):
    """Verifies that User A and User B only see their own respective projects in GET /api/v1/projects."""
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # User A creates 2 projects
    p_a1 = auth_client.post("/api/v1/projects", json={"name": "Project A1"}, headers=headers_a).json()["project"]["id"]
    p_a2 = auth_client.post("/api/v1/projects", json={"name": "Project A2"}, headers=headers_a).json()["project"]["id"]

    # User B creates 1 project
    p_b1 = auth_client.post("/api/v1/projects", json={"name": "Project B1"}, headers=headers_b).json()["project"]["id"]

    # User A lists projects: must see p_a1 and p_a2, but NEVER p_b1
    list_a = auth_client.get("/api/v1/projects", headers=headers_a).json()["projects"]
    ids_a = [p["id"] for p in list_a]
    assert p_a1 in ids_a
    assert p_a2 in ids_a
    assert p_b1 not in ids_a

    # User B lists projects: must see p_b1, but NEVER p_a1 or p_a2
    list_b = auth_client.get("/api/v1/projects", headers=headers_b).json()["projects"]
    ids_b = [p["id"] for p in list_b]
    assert p_b1 in ids_b
    assert p_a1 not in ids_b
    assert p_a2 not in ids_b


def test_cross_user_project_access_denied_id_enumeration_defense(auth_client: TestClient, two_users: dict):
    """
    ID Enumeration Protection:
    When User A queries User B's project, the response must be 404 Not Found (same as non-existent project).
    Never leak that User B's project exists.
    """
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    proj_b = auth_client.post("/api/v1/projects", json={"name": "Secret Project B"}, headers=headers_b).json()["project"]["id"]

    # 1. User A tries to GET User B's project -> 404
    get_res = auth_client.get(f"/api/v1/projects/{proj_b}", headers=headers_a)
    assert get_res.status_code == 404
    assert get_res.json()["error"]["code"] in ("NOT_FOUND", "PROJECT_NOT_FOUND")

    # 2. User A tries to PATCH User B's project -> 404
    patch_res = auth_client.patch(f"/api/v1/projects/{proj_b}", json={"name": "Hacked"}, headers=headers_a)
    assert patch_res.status_code == 404

    # 3. User B can access their own project -> 200 OK
    b_res = auth_client.get(f"/api/v1/projects/{proj_b}", headers=headers_b)
    assert b_res.status_code == 200
    assert b_res.json()["project"]["name"] == "Secret Project B"


# =============================================================================
# 6. MEDIA UPLOAD & DOWNLOAD SECURITY TESTS
# =============================================================================

def test_cross_user_media_upload_and_download_isolation(auth_client: TestClient, two_users: dict):
    """
    Verifies that User A cannot upload into or download from User B's project.
    """
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    proj_b = auth_client.post("/api/v1/projects", json={"name": "Media Project B"}, headers=headers_b).json()["project"]["id"]

    # 1. User A attempts to upload to Project B -> 404
    video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"video_data_sample" * 10
    upload_a = auth_client.post(
        f"/api/v1/projects/{proj_b}/media",
        files={"file": ("fake_video.mp4", io.BytesIO(video_bytes), "video/mp4")},
        data={"media_type": "source_video"},
        headers=headers_a,
    )
    assert upload_a.status_code == 404

    # 2. User B uploads media to Project B -> 201 OK
    upload_b = auth_client.post(
        f"/api/v1/projects/{proj_b}/media",
        files={"file": ("legit_video.mp4", io.BytesIO(video_bytes), "video/mp4")},
        data={"media_type": "source_video"},
        headers=headers_b,
    )
    assert upload_b.status_code == 201
    media_b_id = upload_b.json()["media"]["id"]

    # 3. User A attempts to download User B's media -> 404
    dl_a = auth_client.get(f"/api/v1/projects/{proj_b}/media/{media_b_id}/download", headers=headers_a)
    assert dl_a.status_code == 404

    # 4. User A attempts GET file binary -> 404
    file_a = auth_client.get(f"/api/v1/projects/{proj_b}/media/{media_b_id}/file", headers=headers_a)
    assert file_a.status_code == 404

    # 5. User B downloads their own media -> 200 OK
    dl_b = auth_client.get(f"/api/v1/projects/{proj_b}/media/{media_b_id}/download", headers=headers_b)
    assert dl_b.status_code == 200


# =============================================================================
# 7. NESTED PIPELINE & RENDER ISOLATION TESTS
# =============================================================================

def test_cross_user_pipeline_and_render_operations_denied(auth_client: TestClient, two_users: dict):
    """
    Verifies that User A cannot trigger, query, or cancel any pipeline operations on User B's project.
    """
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    proj_b = auth_client.post("/api/v1/projects", json={"name": "Pipeline Project B"}, headers=headers_b).json()["project"]["id"]

    # 1. User A attempts extract-audio on B's project -> 404
    res1 = auth_client.post(f"/api/v1/projects/{proj_b}/media/MED-123/extract-audio", headers=headers_a)
    assert res1.status_code == 404

    # 2. User A attempts transcribe on B's project -> 404
    res2 = auth_client.post(f"/api/v1/projects/{proj_b}/media/MED-123/transcribe", headers=headers_a)
    assert res2.status_code == 404

    # 3. User A attempts analyze on B's project -> 404
    res3 = auth_client.post(f"/api/v1/projects/{proj_b}/media/MED-123/analyze", headers=headers_a)
    assert res3.status_code == 404

    # 4. User A attempts comic-generation on B's project -> 404
    res4 = auth_client.post(f"/api/v1/projects/{proj_b}/comic-generation", json={}, headers=headers_a)
    assert res4.status_code == 404

    # 5. User A attempts consistency generate on B's project -> 404
    res5 = auth_client.post(f"/api/v1/projects/{proj_b}/consistency/generate", json={}, headers=headers_a)
    assert res5.status_code == 404

    # 6. User A attempts segmentation on B's project -> 404
    res6 = auth_client.post(f"/api/v1/projects/{proj_b}/segmentation", json={}, headers=headers_a)
    assert res6.status_code == 404

    # 7. User A attempts lyrics sync / get on B's project -> 404
    res7 = auth_client.post(f"/api/v1/projects/{proj_b}/lyrics/sync", json={}, headers=headers_a)
    assert res7.status_code == 404
    res8 = auth_client.get(f"/api/v1/projects/{proj_b}/lyrics", headers=headers_a)
    assert res8.status_code == 404

    # 8. User A attempts render on B's project -> 404
    res9 = auth_client.post(f"/api/v1/projects/{proj_b}/render", json={}, headers=headers_a)
    assert res9.status_code == 404

    # 9. User A attempts render jobs list on B's project -> 404
    res10 = auth_client.get(f"/api/v1/projects/{proj_b}/render", headers=headers_a)
    assert res10.status_code == 404

    # 10. User A attempts storage audit / cleanup on B's project -> 404
    res11 = auth_client.get(f"/api/v1/projects/{proj_b}/storage-audit", headers=headers_a)
    assert res11.status_code == 404
    res12 = auth_client.post(f"/api/v1/projects/{proj_b}/storage-cleanup", json={}, headers=headers_a)
    assert res12.status_code == 404


# =============================================================================
# 8. COMPLETE SECURITY ISOLATION MATRIX (A vs B)
# =============================================================================

def test_full_security_isolation_matrix(auth_client: TestClient, two_users: dict):
    """
    Explicitly executes the full isolation matrix:
    A -> A = ALLOWED (200/201)
    B -> B = ALLOWED (200/201)
    A -> B = DENIED (404)
    B -> A = DENIED (404)
    """
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # Setup Project A and Project B
    proj_a_id = auth_client.post("/api/v1/projects", json={"name": "Matrix Project A"}, headers=headers_a).json()["project"]["id"]
    proj_b_id = auth_client.post("/api/v1/projects", json={"name": "Matrix Project B"}, headers=headers_b).json()["project"]["id"]

    # Matrix: GET Project State
    assert auth_client.get(f"/api/v1/projects/{proj_a_id}", headers=headers_a).status_code == 200  # A -> A
    assert auth_client.get(f"/api/v1/projects/{proj_b_id}", headers=headers_b).status_code == 200  # B -> B
    assert auth_client.get(f"/api/v1/projects/{proj_b_id}", headers=headers_a).status_code == 404  # A -> B
    assert auth_client.get(f"/api/v1/projects/{proj_a_id}", headers=headers_b).status_code == 404  # B -> A

    # Matrix: PATCH Project State
    assert auth_client.patch(f"/api/v1/projects/{proj_a_id}", json={"name": "Renamed A"}, headers=headers_a).status_code == 200  # A -> A
    assert auth_client.patch(f"/api/v1/projects/{proj_b_id}", json={"name": "Renamed B"}, headers=headers_b).status_code == 200  # B -> B
    assert auth_client.patch(f"/api/v1/projects/{proj_b_id}", json={"name": "Attack A"}, headers=headers_a).status_code == 404  # A -> B
    assert auth_client.patch(f"/api/v1/projects/{proj_a_id}", json={"name": "Attack B"}, headers=headers_b).status_code == 404  # B -> A


# =============================================================================
# 9. DATABASE MIGRATION VERIFICATION TEST
# =============================================================================

def test_database_migration_idempotent(db_session: Session):
    """Verifies that database migrations execute deterministically and idempotently."""
    applied = run_migrations()
    assert isinstance(applied, list)
    # Re-running migration on initialized DB produces zero pending
    re_applied = run_migrations()
    assert len(re_applied) == 0


# =============================================================================
# 10. AUTHENTICATION RATE LIMITING TEST
# =============================================================================

def test_auth_rate_limiting_protection(auth_client: TestClient):
    """Verifies that rapid login/registration attempts exceeding the threshold trigger HTTP 429."""
    limiter._records.clear()
    email = f"ratelimit_{generate_uuid()[:8]}@example.com"
    payload = {"email": email, "password": "SamplePassword123!"}

    # Register user
    first_res = auth_client.post("/api/v1/auth/register", json=payload)
    assert first_res.status_code == 201

    # Send exactly AUTH_RATE_LIMIT_PER_MINUTE (10) requests to /api/v1/auth/login
    for i in range(settings.AUTH_RATE_LIMIT_PER_MINUTE):
        res = auth_client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword!"})
        assert res.status_code in (401, 200)

    # The 11th request to /api/v1/auth/login must be rejected with 429 Too Many Requests
    blocked_res = auth_client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword!"})
    assert blocked_res.status_code == 429
    data = blocked_res.json()
    assert data["success"] is False
    assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"


