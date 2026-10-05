"""
3D Reel Studio — Database Engine and Session Management
Phase 3: Project Session Persistence
"""

from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logging import logger

# Ensure database storage directory exists
if settings.DATABASE_URL.startswith("sqlite"):
    # Extract file path from sqlite:///...
    db_path_str = settings.DATABASE_URL.replace("sqlite:///", "")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        # Relative to backend root
        backend_root = Path(__file__).resolve().parent.parent.parent
        db_path = backend_root / db_path_str
        # Update DATABASE_URL to absolute or normalized path
        resolved_url = f"sqlite:///{db_path.as_posix()}"
    else:
        resolved_url = settings.DATABASE_URL
    
    # Create parent folder if not present
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        resolved_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    """
    Initializes database tables and executes deterministic forward migrations.
    Safe to run repeatedly; never deletes or overwrites existing data.
    """
    try:
        from app.db.migrations import run_migrations
        applied = run_migrations(target_engine=engine)
        if applied:
            logger.info(f"Database migrations applied: {applied}")
        logger.info(f"Database schema initialized successfully on {settings.DATABASE_URL}")
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}", exc_info=True)
        raise


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding database session per request.
    Ensures sessions are cleanly closed when requests complete.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
