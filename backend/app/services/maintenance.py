"""
3D Reel Studio — System Maintenance, Diagnostic Storage Audit & Job Reconciliation
Phase 14: Production Hardening
"""

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models.project import (
    ComicGeneration,
    ConsistencyGeneration,
    MediaFile,
    Project,
    RenderJob,
    SegmentationResult,
    TransformationJob,
    utc_now,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir


def compute_file_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hex digest of a file safely."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def reconcile_stale_jobs_on_startup(db: Session) -> Dict[str, int]:
    """
    Scans for any background jobs stuck in 'processing' or 'queued' state from a previous server run
    and reconciles them to 'failed' with a clear, safe recovery message.
    """
    reconciled_counts = {
        "render_jobs": 0,
        "transformation_jobs": 0,
        "comic_generations": 0,
        "consistency_generations": 0,
        "segmentation_results": 0,
    }

    try:
        # 1. Render Jobs
        stale_renders = (
            db.query(RenderJob)
            .filter(RenderJob.status.in_(["processing", "queued"]))
            .all()
        )
        for job in stale_renders:
            job.status = "failed"
            job.error_code = "SERVER_RESTARTED_RECOVERY"
            job.error_message = "Render was interrupted by a server restart. Please trigger a new render."
            job.stage_message = "Interrupted by server restart."
            job.completed_at = utc_now()
            reconciled_counts["render_jobs"] += 1

        # 2. Transformation Jobs
        stale_transformations = (
            db.query(TransformationJob)
            .filter(TransformationJob.status.in_(["processing", "queued"]))
            .all()
        )
        for job in stale_transformations:
            job.status = "failed"
            job.error_message = "Job was interrupted by a server restart."
            reconciled_counts["transformation_jobs"] += 1

        # 3. Comic Generations
        stale_comics = (
            db.query(ComicGeneration)
            .filter(ComicGeneration.status.in_(["processing", "queued"]))
            .all()
        )
        for gen in stale_comics:
            gen.status = "failed"
            gen.error_message = "Generation interrupted by server restart."
            reconciled_counts["comic_generations"] += 1

        # 4. Consistency Generations
        stale_consistency = (
            db.query(ConsistencyGeneration)
            .filter(ConsistencyGeneration.status.in_(["processing", "queued"]))
            .all()
        )
        for gen in stale_consistency:
            gen.status = "failed"
            gen.error_message = "Consistency generation interrupted by server restart."
            reconciled_counts["consistency_generations"] += 1

        # 5. Segmentation Results
        stale_segs = (
            db.query(SegmentationResult)
            .filter(SegmentationResult.status.in_(["processing", "queued"]))
            .all()
        )
        for seg in stale_segs:
            seg.status = "failed"
            seg.error_code = "SERVER_RESTARTED_RECOVERY"
            reconciled_counts["segmentation_results"] += 1

        if any(c > 0 for c in reconciled_counts.values()):
            db.commit()
            logger.info(f"Reconciled stale background jobs on startup: {reconciled_counts}")
        else:
            logger.info("Startup job reconciliation: zero stale processing jobs found.")

    except Exception as e:
        logger.error(f"Error during startup job reconciliation: {e}")
        db.rollback()

    return reconciled_counts


def audit_project_storage(db: Session, project_id: str) -> Dict[str, Any]:
    """
    Performs a non-destructive diagnostic audit of project storage:
    - Validates all database MediaFile records against files on disk.
    - Checks for missing files, zero-byte corrupted files, and checksum discrepancies.
    - Scans disk directory for unreferenced files or stale temporary folders.
    """
    clean_id = project_id.strip()
    base_storage = get_base_storage_dir()
    proj_dir = base_storage / "projects" / clean_id

    media_records = db.query(MediaFile).filter(MediaFile.project_id == clean_id).all()

    missing_files: List[Dict[str, Any]] = []
    zero_byte_files: List[Dict[str, Any]] = []
    checksum_mismatches: List[Dict[str, Any]] = []
    healthy_files: List[Dict[str, Any]] = []
    referenced_disk_paths = set()

    for mf in media_records:
        path = Path(mf.file_path)
        referenced_disk_paths.add(str(path.resolve()) if path.exists() else str(path))

        if not path.is_file():
            missing_files.append({
                "media_id": mf.id,
                "file_type": mf.file_type,
                "expected_path": mf.file_path,
                "original_filename": mf.original_filename,
            })
            continue

        size = path.stat().st_size
        if size == 0:
            zero_byte_files.append({
                "media_id": mf.id,
                "file_type": mf.file_type,
                "file_path": mf.file_path,
            })
            continue

        if mf.sha256_hash:
            actual_hash = compute_file_sha256(path)
            if actual_hash != mf.sha256_hash:
                checksum_mismatches.append({
                    "media_id": mf.id,
                    "expected_hash": mf.sha256_hash,
                    "actual_hash": actual_hash,
                    "file_path": mf.file_path,
                })
                continue

        healthy_files.append({
            "media_id": mf.id,
            "file_type": mf.file_type,
            "file_size": size,
            "original_filename": mf.original_filename,
        })

    # Scan disk for unreferenced files and stale temp dirs
    unreferenced_files: List[Dict[str, Any]] = []
    stale_temp_dirs: List[str] = []

    if proj_dir.is_dir():
        for root, dirs, files in os.walk(proj_dir):
            root_path = Path(root)
            if "tmp_job_" in root_path.name:
                stale_temp_dirs.append(str(root_path))
                continue

            for f in files:
                file_full_path = (root_path / f).resolve()
                if str(file_full_path) not in referenced_disk_paths:
                    unreferenced_files.append({
                        "file_path": str(file_full_path),
                        "file_size": file_full_path.stat().st_size,
                        "relative_path": str(file_full_path.relative_to(proj_dir)),
                    })

    is_healthy = len(missing_files) == 0 and len(zero_byte_files) == 0 and len(checksum_mismatches) == 0

    return {
        "project_id": clean_id,
        "is_healthy": is_healthy,
        "summary": {
            "total_media_records": len(media_records),
            "healthy_count": len(healthy_files),
            "missing_count": len(missing_files),
            "zero_byte_count": len(zero_byte_files),
            "checksum_mismatch_count": len(checksum_mismatches),
            "unreferenced_disk_files_count": len(unreferenced_files),
            "stale_temp_dirs_count": len(stale_temp_dirs),
        },
        "missing_files": missing_files,
        "zero_byte_files": zero_byte_files,
        "checksum_mismatches": checksum_mismatches,
        "unreferenced_files": unreferenced_files,
        "stale_temp_dirs": stale_temp_dirs,
    }


def cleanup_project_storage(
    db: Session,
    project_id: str,
    dry_run: bool = True,
    clean_stale_temp: bool = True,
    clean_unreferenced: bool = False,
) -> Dict[str, Any]:
    """
    Safely cleans up stale temporary directories or orphaned files.
    Defaults to dry_run=True to ensure no destructive actions occur without explicit confirmation.
    """
    audit = audit_project_storage(db, project_id)
    actions_taken: List[Dict[str, Any]] = []

    if clean_stale_temp:
        for temp_dir_str in audit.get("stale_temp_dirs", []):
            p = Path(temp_dir_str)
            if p.is_dir() and "tmp_job_" in p.name:
                if not dry_run:
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        actions_taken.append({"action": "deleted_temp_dir", "path": str(p)})
                    except Exception as e:
                        actions_taken.append({"action": "error_deleting_temp_dir", "path": str(p), "error": str(e)})
                else:
                    actions_taken.append({"action": "would_delete_temp_dir", "path": str(p)})

    if clean_unreferenced:
        for unref in audit.get("unreferenced_files", []):
            p = Path(unref["file_path"])
            if p.is_file():
                if not dry_run:
                    try:
                        p.unlink(missing_ok=True)
                        actions_taken.append({"action": "deleted_unreferenced_file", "path": str(p)})
                    except Exception as e:
                        actions_taken.append({"action": "error_deleting_unreferenced_file", "path": str(p), "error": str(e)})
                else:
                    actions_taken.append({"action": "would_delete_unreferenced_file", "path": str(p)})

    return {
        "project_id": project_id,
        "dry_run": dry_run,
        "actions_taken": actions_taken,
        "audit_after": audit if dry_run else audit_project_storage(db, project_id),
    }
