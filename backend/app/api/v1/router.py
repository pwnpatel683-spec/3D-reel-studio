"""
3D Reel Studio — Central v1 Router Aggregator
Phase 2, Phase 3 & Phase 4: FastAPI Backend, Project Session Persistence & Media Upload Storage
"""

from fastapi import APIRouter
from app.api.v1 import auth, health, projects

api_v1_router = APIRouter()

# Authentication & User Accounts (Phase 16)
api_v1_router.include_router(auth.router)

# Core Health and Status Endpoints
api_v1_router.include_router(health.router)

# Project Session Persistence Endpoints (Phase 3 & 16)
api_v1_router.include_router(projects.router)

# ===================================================================
# PLACEHOLDERS FOR FUTURE PHASE SUB-ROUTERS:
# ===================================================================
# - Phase 4: api_v1_router.include_router(media.router, prefix="/media", tags=["Media Processing"])
# - Phase 5: api_v1_router.include_router(transcription.router, prefix="/transcription", tags=["Whisper AI"])
# - Phase 6: api_v1_router.include_router(generation.router, prefix="/generate", tags=["3D Generation Engine"])
# - Phase 10: api_v1_router.include_router(lyrics.router, prefix="/lyrics", tags=["Kinetic Lyrics Engine"])
