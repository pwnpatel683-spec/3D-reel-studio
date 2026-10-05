"""
3D Reel Studio — Cryptographic Security & Authentication Engine
Phase 16: Multi-User Authentication & Security Hardening
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from app.core.config import settings
from app.core.logging import logger
from app.core.rate_limit import limiter


# -----------------------------------------------------------------------------
# Constant-Time Password Hashing Engine (PBKDF2-HMAC-SHA256)
# -----------------------------------------------------------------------------
PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_DEFAULT_ITERATIONS = 600000  # OWASP recommendation for PBKDF2-SHA256
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """
    Hashes a plain-text password using cryptographically secure PBKDF2-HMAC-SHA256
    with a fresh 16-byte random salt and 600,000 iterations.
    
    Output Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    
    salt = secrets.token_bytes(SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt,
        iterations=PBKDF2_DEFAULT_ITERATIONS,
    )
    salt_hex = salt.hex()
    hash_hex = derived_key.hex()
    return f"{PBKDF2_ALGORITHM}${PBKDF2_DEFAULT_ITERATIONS}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plain-text password against a stored PBKDF2 hash using
    constant-time comparison to prevent timing side-channel attacks.
    """
    if not plain_password or not hashed_password:
        return False

    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != PBKDF2_ALGORITHM:
            return False

        _, iterations_str, salt_hex, expected_hash_hex = parts
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)

        candidate_key = hashlib.pbkdf2_hmac(
            hash_name="sha256",
            password=plain_password.encode("utf-8"),
            salt=salt,
            iterations=iterations,
        )
        candidate_hash_hex = candidate_key.hex()
        return hmac.compare_digest(candidate_hash_hex, expected_hash_hex)
    except Exception as e:
        logger.warning(f"Password verification encountered malformed hash structure: {e}")
        return False


# -----------------------------------------------------------------------------
# Base64URL Encoding Utilities
# -----------------------------------------------------------------------------
def _b64_url_encode(data: bytes) -> str:
    """Encodes bytes to unpadded URL-safe Base64."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_url_decode(encoded: str) -> bytes:
    """Decodes unpadded URL-safe Base64 string to bytes."""
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


# -----------------------------------------------------------------------------
# Tamper-Proof Signed JWT Token Engine
# -----------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Creates a tamper-proof HMAC-SHA256 signed access token (JWT format).
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    header = {
        "alg": settings.AUTH_ALGORITHM or "HS256",
        "typ": "JWT",
    }
    payload = {
        "sub": user_id,
        "email": email.strip().lower(),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.APP_NAME,
    }

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    header_b64 = _b64_url_encode(header_bytes)
    payload_b64 = _b64_url_encode(payload_bytes)
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    secret_key = settings.AUTH_SECRET.encode("utf-8")
    signature = hmac.new(secret_key, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64_url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decodes and verifies the signature and expiration of an access token.
    Returns payload dictionary if valid, or None if invalid/expired.
    """
    if not token or not isinstance(token, str):
        return None

    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts

    try:
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        secret_key = settings.AUTH_SECRET.encode("utf-8")
        expected_sig = hmac.new(secret_key, signing_input, hashlib.sha256).digest()
        provided_sig = _b64_url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            logger.warning("Token verification failed: signature mismatch")
            return None

        payload_bytes = _b64_url_decode(payload_b64)
        payload: Dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))

        # Expiration validation
        exp = payload.get("exp")
        if not exp or not isinstance(exp, (int, float)):
            return None

        now_ts = int(time.time())
        if now_ts > exp:
            logger.debug(f"Token verification failed: expired (now={now_ts}, exp={exp})")
            return None

        # Ensure user identifier exists
        if not payload.get("sub"):
            return None

        return payload
    except Exception as e:
        logger.warning(f"Error decoding access token: {e}")
        return None


# -----------------------------------------------------------------------------
# Rate Limiting Dependency for Authentication Endpoints
# -----------------------------------------------------------------------------
def rate_limit_auth(request: Request) -> None:
    """
    FastAPI dependency applying rate limits to sensitive auth endpoints (login/register).
    """
    limiter.check(request, max_requests=settings.AUTH_RATE_LIMIT_PER_MINUTE)
