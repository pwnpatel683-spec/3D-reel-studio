"""
3D Reel Studio — Deterministic Database Migrations Engine
Phase 15: Production Deployment
"""

import sys
from datetime import datetime, timezone
from typing import List, Tuple
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.core.logging import logger
from app.db.session import Base, engine


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_migration_table(conn) -> None:
    """Creates the schema_migrations tracking table if not present."""
    if settings.DATABASE_URL.startswith("sqlite"):
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                applied_at VARCHAR(64) NOT NULL,
                description VARCHAR(255)
            )
        """))
    else:  # PostgreSQL / generic SQL
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                applied_at VARCHAR(64) NOT NULL,
                description VARCHAR(255)
            )
        """))
    conn.commit()


def get_applied_migrations(conn) -> List[str]:
    """Retrieves list of already applied migration version strings."""
    ensure_migration_table(conn)
    result = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version ASC"))
    return [row[0] for row in result.fetchall()]


def record_migration(conn, version: str, description: str) -> None:
    """Records an applied migration version in the database."""
    conn.execute(
        text("INSERT INTO schema_migrations (version, applied_at, description) VALUES (:v, :t, :d)"),
        {"v": version, "t": utc_now_iso(), "d": description},
    )
    conn.commit()


# -----------------------------------------------------------------------------
# Migration Step Definitions
# -----------------------------------------------------------------------------


def migration_001_initial_tables(conn, target_engine: Engine) -> None:
    """
    Migration 001: Initial baseline schema creation.
    Safely creates all tables using SQLAlchemy metadata if not present.
    """
    from app.models import (  # noqa: F401
        Project,
        MediaFile,
        TransformationJob,
        Transcript,
        TranscriptSegment,
        VideoAnalysis,
        VideoScene,
        SceneKeyframe,
        VisionAnalysis,
        DetectedSubject,
        FaceDetection,
        FaceReference,
        PoseDetection,
        ComicGeneration,
        ComicFrame,
        CharacterConsistencyProfile,
        ConsistencyGeneration,
        ConsistentComicFrame,
        SegmentationResult,
        LyricStyle,
        LyricAnimation,
        LyricSegment,
        LyricPreview,
        RenderJob,
    )
    Base.metadata.create_all(bind=target_engine)


def migration_002_performance_indexes(conn, target_engine: Engine) -> None:
    """
    Migration 002: Adds optimized composite performance indexes for project queries.
    """
    indexes = [
        ("ix_media_files_project_type", "CREATE INDEX IF NOT EXISTS ix_media_files_project_type ON media_files (project_id, file_type)"),
        ("ix_render_jobs_project_status", "CREATE INDEX IF NOT EXISTS ix_render_jobs_project_status ON render_jobs (project_id, status)"),
        ("ix_video_scenes_analysis_seq", "CREATE INDEX IF NOT EXISTS ix_video_scenes_analysis_seq ON video_scenes (analysis_id, sequence)"),
        ("ix_lyric_segments_project_seq", "CREATE INDEX IF NOT EXISTS ix_lyric_segments_project_seq ON lyric_segments (project_id, sequence)"),
    ]
    for idx_name, idx_sql in indexes:
        try:
            conn.execute(text(idx_sql))
            conn.commit()
        except Exception as e:
            logger.debug(f"Index creation note ({idx_name}): {e}")


def migration_003_user_auth_and_project_ownership(conn, target_engine: Engine) -> None:
    """
    Migration 003: Creates users table, adds project ownership (user_id),
    creates indexes, and safely backfills any orphaned legacy development projects.
    """
    from app.core.security import hash_password
    from app.models.user import User  # noqa: F401
    
    # 1. Ensure User model table is created
    Base.metadata.create_all(bind=target_engine)

    # 2. Add user_id column to projects table if missing
    inspector = inspect(target_engine)
    project_cols = [c["name"] for c in inspector.get_columns("projects")]
    if "user_id" not in project_cols:
        logger.info("Adding 'user_id' column to projects table...")
        try:
            conn.execute(text("ALTER TABLE projects ADD COLUMN user_id VARCHAR(64)"))
            conn.commit()
        except Exception as e:
            logger.warning(f"Note while adding user_id column: {e}")

    # 3. Create indexes on users and projects
    indexes = [
        ("ix_users_email", "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"),
        ("ix_projects_user_id", "CREATE INDEX IF NOT EXISTS ix_projects_user_id ON projects (user_id)"),
    ]
    for idx_name, idx_sql in indexes:
        try:
            conn.execute(text(idx_sql))
            conn.commit()
        except Exception as e:
            logger.debug(f"Index creation note ({idx_name}): {e}")

    # 4. Safe legacy backfill: check for projects with null user_id
    try:
        orphaned_count_res = conn.execute(text("SELECT COUNT(*) FROM projects WHERE user_id IS NULL"))
        orphaned_count = orphaned_count_res.scalar() or 0
        if orphaned_count > 0:
            logger.info(f"Found {orphaned_count} legacy projects without owner. Backfilling to default dev user...")
            
            # Check or create default dev user
            dev_user_row = conn.execute(text("SELECT id FROM users WHERE email = 'dev@3dreelstudio.local'")).fetchone()
            if not dev_user_row:
                dev_user_id = "USR-DEFAULT-DEV"
                dev_pw_hash = hash_password("DevStudio2026!")
                conn.execute(
                    text("""
                        INSERT INTO users (id, email, password_hash, is_active, created_at, updated_at)
                        VALUES (:uid, 'dev@3dreelstudio.local', :pwhash, 1, :now, :now)
                    """),
                    {"uid": dev_user_id, "pwhash": dev_pw_hash, "now": datetime.now(timezone.utc)},
                )
                conn.commit()
            else:
                dev_user_id = dev_user_row[0]

            conn.execute(
                text("UPDATE projects SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": dev_user_id},
            )
            conn.commit()
            logger.info(f"Backfilled {orphaned_count} legacy projects to owner '{dev_user_id}'.")
    except Exception as e:
        logger.warning(f"Backfill note: {e}")


MIGRATIONS: List[Tuple[str, str, callable]] = [
    ("001_initial_tables", "Initial schema with 24 relational tables", migration_001_initial_tables),
    ("002_performance_indexes", "Composite performance indexes for faster pipeline queries", migration_002_performance_indexes),
    ("003_user_auth_and_project_ownership", "User authentication and project ownership isolation", migration_003_user_auth_and_project_ownership),
]



def run_migrations(target_engine: Engine = engine) -> List[str]:
    """
    Executes all pending database migrations in forward order.
    Returns list of newly applied migration versions.
    """
    applied_now: List[str] = []
    with target_engine.connect() as conn:
        applied = set(get_applied_migrations(conn))
        for version, description, func in MIGRATIONS:
            if version not in applied:
                logger.info(f"Applying database migration '{version}': {description}...")
                func(conn, target_engine)
                record_migration(conn, version, description)
                applied_now.append(version)
                logger.info(f"Migration '{version}' applied successfully.")
            else:
                logger.debug(f"Migration '{version}' already applied.")

    return applied_now


def migration_status(target_engine: Engine = engine) -> List[dict]:
    """Returns the current status of all migrations."""
    with target_engine.connect() as conn:
        applied = set(get_applied_migrations(conn))
        status_list = []
        for version, description, _ in MIGRATIONS:
            status_list.append({
                "version": version,
                "description": description,
                "applied": version in applied,
            })
        return status_list


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    if action == "status":
        print("=== Database Migration Status ===")
        for item in migration_status():
            mark = "[X]" if item["applied"] else "[ ]"
            print(f"{mark} {item['version']}: {item['description']}")
    elif action in ("migrate", "init"):
        print(f"Connecting to database: {settings.DATABASE_URL}")
        applied_mig = run_migrations()
        if applied_mig:
            print(f"Applied {len(applied_mig)} migration(s): {', '.join(applied_mig)}")
        else:
            print("Database is already up to date. Zero pending migrations.")
    else:
        print(f"Unknown action: {action}. Usage: python -m app.db.migrations [migrate|status|init]")
