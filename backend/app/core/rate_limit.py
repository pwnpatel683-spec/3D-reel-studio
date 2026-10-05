"""
3D Reel Studio — Lightweight In-Memory Rate Limiting
Phase 15: Production Deployment & Abuse Protection
"""

import time
from collections import defaultdict
from typing import Dict, List
from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.logging import logger


class InMemoryRateLimiter:
    """
    Sliding window rate limiter tracking request timestamps per client IP.
    Protects expensive AI and rendering pipeline endpoints against accidental request bursts.
    """

    def __init__(self, requests_per_minute: int = 60, window_seconds: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self._records: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_key: str, max_requests: int) -> bool:
        now = time.time()
        window_start = now - self.window_seconds

        # Prune older timestamps
        timestamps = [t for t in self._records[client_key] if t > window_start]
        self._records[client_key] = timestamps

        if len(timestamps) >= max_requests:
            return False

        self._records[client_key].append(now)
        return True

    def check(self, request: Request, max_requests: int = 60) -> None:
        client_ip = request.client.host if request.client else "unknown_client"
        endpoint = request.url.path

        # In testing or debug mode with localhost, remain permissive unless explicitly configured
        effective_limit = max_requests or settings.RATE_LIMIT_REQUESTS_PER_MINUTE

        key = f"{client_ip}:{endpoint}"
        if not self.is_allowed(key, effective_limit):
            logger.warning(f"Rate limit exceeded for client '{client_ip}' on endpoint '{endpoint}' ({effective_limit}/min)")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded ({effective_limit} requests per minute). Please slow down.",
                },
            )


# Global rate limiter instances
limiter = InMemoryRateLimiter()


def rate_limit_expensive(request: Request) -> None:
    """FastAPI dependency for expensive AI, transcode, and rendering operations (e.g. 30 req/min)."""
    limiter.check(request, max_requests=30)
