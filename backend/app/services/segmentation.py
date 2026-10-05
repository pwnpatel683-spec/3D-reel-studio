"""
3D Reel Studio — Foreground Segmentation & Dynamic Background Service
Phase 11: Foreground Segmentation + Dynamic Background

Isolates the primary subject character from the 3D comic frame, generates a
refined soft alpha mask, inpaint-reconstructs the clean background layer,
applies dynamic background adaptation modes (ORIGINAL, SOFT_BLUR, DEPTH_STYLE, COMIC_STYLE),
and outputs independently compositable layer assets.
"""

import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.project import (
    ComicFrame,
    ConsistentComicFrame,
    DetectedSubject,
    FaceDetection,
    MediaFile,
    PoseDetection,
    Project,
    SceneKeyframe,
    SegmentationResult,
    VideoAnalysis,
    VideoScene,
    VisionAnalysis,
)
from app.services.storage import get_base_storage_dir, get_project_storage_dir

logger = logging.getLogger("comic_studio.segmentation")


def utc_now() -> datetime:
    """Returns current UTC timestamp timezone-aware."""
    return datetime.now(timezone.utc)


# -----------------------------------------------------------------------------
# 1. Output Data Structure & Abstract Provider
# -----------------------------------------------------------------------------

@dataclass
class SegmentationOutput:
    """
    Standard output payload returned by segmentation providers.
    """
    foreground_rgba: np.ndarray  # (H, W, 4) uint8 RGBA
    mask_alpha: np.ndarray       # (H, W) uint8 Grayscale 0-255
    bbox: Tuple[float, float, float, float]  # (x, y, w, h) normalized [0.0, 1.0]
    quality_metrics: Dict[str, Any]


class ForegroundSegmentationProvider(ABC):
    """
    Abstract Base Class for Foreground Segmentation models/providers.
    Decouples the pipeline from concrete segmentation engines.
    """
    provider_name: str = "abstract"
    model_name: str = "base"

    @abstractmethod
    def segment_foreground(
        self,
        image_np: np.ndarray,
        subject_guide: Optional[Dict[str, Any]] = None,
        refinement_params: Optional[Dict[str, Any]] = None,
    ) -> SegmentationOutput:
        """
        Segments the primary subject from the input RGB image.
        
        Args:
            image_np: (H, W, 3) uint8 BGR or RGB image.
            subject_guide: Optional dictionary containing face bounding box and pose landmarks.
            refinement_params: Optional dictionary of mask refinement parameters.
            
        Returns:
            SegmentationOutput containing foreground RGBA, alpha mask, bbox, and quality metrics.
        """
        pass


# -----------------------------------------------------------------------------
# 2. Mask Refinement & Quality Scoring Utilities
# -----------------------------------------------------------------------------

def refine_mask(
    raw_mask: np.ndarray,
    refinement_params: Optional[Dict[str, Any]] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Applies configurable morphological refinement, hole filling, small component
    filtering, and soft edge feathering to the raw segmentation mask.
    
    Preserves fine contours (hair silhouette, fingers, clothing folds) while
    removing background leakage and internal holes.
    """
    params = refinement_params or {}
    morph_kernel_size = int(params.get("morph_kernel_size", 3))
    hole_fill = bool(params.get("hole_fill", True))
    blur_radius = int(params.get("blur_radius", 3))
    min_component_ratio = float(params.get("min_component_ratio", 0.02))

    h, w = raw_mask.shape[:2]
    total_pixels = h * w

    # Ensure binary uint8 (0 or 255)
    _, binary_mask = cv2.threshold(raw_mask, 127, 255, cv2.THRESH_BINARY)

    # 1. Morphological Closing to seal hairline gaps and contour notches
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size))
    closed_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, k_close, iterations=2)

    # 2. Hole filling (internal body voids surrounded by foreground)
    filled_mask = closed_mask.copy()
    if hole_fill:
        contours, hierarchy = cv2.findContours(closed_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is not None:
            for i, h_info in enumerate(hierarchy[0]):
                # If contour is a child hole (has a parent)
                if h_info[3] >= 0:
                    cv2.drawContours(filled_mask, contours, i, 255, -1)

    # 3. Small-component removal (eliminate isolated background noise)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(filled_mask, connectivity=8)
    clean_mask = np.zeros_like(filled_mask)
    min_area = int(total_pixels * min_component_ratio)

    if num_labels > 1:
        # Sort components by area excluding background (label 0)
        component_areas = [(i, stats[i, cv2.CC_STAT_AREA]) for i in range(1, num_labels)]
        component_areas.sort(key=lambda x: x[1], reverse=True)

        # Retain the largest component and any significant secondary component (> min_area)
        for idx, area in component_areas:
            if area >= min_area or idx == component_areas[0][0]:
                clean_mask[labels == idx] = 255
    else:
        clean_mask = filled_mask

    # 4. Soft Edge Feathering / Anti-aliasing
    if blur_radius > 0:
        # Create a soft transition band at the boundary
        k_blur = blur_radius if blur_radius % 2 != 0 else blur_radius + 1
        feathered_mask = cv2.GaussianBlur(clean_mask.astype(np.float32), (k_blur, k_blur), 0)
        # Re-scale transition to 0-255 uint8
        soft_mask = np.clip(feathered_mask, 0, 255).astype(np.uint8)
    else:
        soft_mask = clean_mask

    # 5. Compute Genuine Mask Quality Metrics
    fg_pixels = int(np.count_nonzero(soft_mask > 128))
    coverage_ratio = float(fg_pixels / total_pixels) if total_pixels > 0 else 0.0

    # Edge gradient smoothness (Sobel energy on border)
    edges = cv2.Canny(clean_mask, 100, 200)
    edge_pixel_count = int(np.count_nonzero(edges))
    edge_smoothness = float(1.0 - min(edge_pixel_count / max(total_pixels * 0.05, 1), 1.0))

    # Overall calculated quality score (0.0 to 1.0)
    coverage_score = 1.0 - min(abs(coverage_ratio - 0.40) / 0.40, 0.8)
    quality_score = float(np.clip(coverage_score * 0.6 + edge_smoothness * 0.4, 0.50, 0.99))

    metrics = {
        "coverage_ratio": round(coverage_ratio, 4),
        "edge_pixel_count": int(edge_pixel_count),
        "edge_smoothness": round(edge_smoothness, 4),
        "quality_score": round(quality_score, 4),
        "foreground_pixels": int(fg_pixels),
        "total_pixels": int(total_pixels),
    }

    return soft_mask, metrics


def compute_mask_bounding_box(mask: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Computes normalized (x, y, w, h) bounding box for the non-zero region of the mask.
    """
    h, w = mask.shape[:2]
    coords = cv2.findNonZero((mask > 50).astype(np.uint8))
    if coords is None or len(coords) == 0:
        return (0.0, 0.0, 1.0, 1.0)

    x, y, box_w, box_h = cv2.boundingRect(coords)
    return (
        round(float(x / w), 4),
        round(float(y / h), 4),
        round(float(box_w / w), 4),
        round(float(box_h / h), 4),
    )


# -----------------------------------------------------------------------------
# 3. OpenCV Subject-Guided Segmentation Provider (GrabCut + Face/Pose Prior)
# -----------------------------------------------------------------------------

class OpenCVSubjectGuidedSegmentationProvider(ForegroundSegmentationProvider):
    """
    Fast, deterministic, and highly effective foreground segmentation provider
    guided by Phase 8 face locations, body pose landmarks, and color priors.
    Runs completely in-process using OpenCV with zero heavy model downloads.
    """
    provider_name: str = "opencv_guided"
    model_name: str = "grabcut_pose_prior"

    def segment_foreground(
        self,
        image_np: np.ndarray,
        subject_guide: Optional[Dict[str, Any]] = None,
        refinement_params: Optional[Dict[str, Any]] = None,
    ) -> SegmentationOutput:
        """
        Executes subject-guided GrabCut segmentation with seeded foreground/background regions.
        """
        if image_np is None or image_np.size == 0:
            raise ValueError("Input image array is empty or invalid.")

        h, w = image_np.shape[:2]
        if image_np.shape[2] == 4:
            bgr = cv2.cvtColor(image_np, cv2.COLOR_RGBA2BGR)
        else:
            bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

        # Initialize GrabCut mask
        # 0: GC_BGD, 1: GC_FGD, 2: GC_PR_BGD, 3: GC_PR_FGD
        gc_mask = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)

        # Determine subject prior box from Phase 8 guide
        face_bbox = subject_guide.get("face_bbox") if subject_guide else None
        pose_landmarks = subject_guide.get("pose_landmarks") if subject_guide else None

        if face_bbox:
            # Expand face box downwards to capture torso and legs
            fx = int(face_bbox.get("x", 0.25) * w)
            fy = int(face_bbox.get("y", 0.15) * h)
            fw = int(face_bbox.get("width", 0.35) * w)
            fh = int(face_bbox.get("height", 0.25) * h)

            # Character ROI: top of head to bottom of frame, shoulders expanded
            roi_x1 = max(0, int(fx - fw * 0.8))
            roi_x2 = min(w, int(fx + fw * 1.8))
            roi_y1 = max(0, int(fy - fh * 0.4))
            roi_y2 = min(h, int(fy + fh * 3.8))
        else:
            # Default center vertical portrait prior
            roi_x1 = int(w * 0.15)
            roi_x2 = int(w * 0.85)
            roi_y1 = int(h * 0.05)
            roi_y2 = int(h * 0.95)

        # Mark Probable Foreground in ROI
        gc_mask[roi_y1:roi_y2, roi_x1:roi_x2] = cv2.GC_PR_FGD

        # Mark outer border margins as Certain Background
        border_x = max(2, int(w * 0.04))
        border_y = max(2, int(h * 0.04))
        gc_mask[0:border_y, :] = cv2.GC_BGD
        gc_mask[h - border_y:h, :] = cv2.GC_BGD
        gc_mask[:, 0:border_x] = cv2.GC_BGD
        gc_mask[:, w - border_x:w] = cv2.GC_BGD

        # Mark Definite Foreground Seeds (Face Core & Pose Spine/Torso)
        if face_bbox:
            face_core_x1 = max(0, int(fx + fw * 0.2))
            face_core_x2 = min(w, int(fx + fw * 0.8))
            face_core_y1 = max(0, int(fy + fh * 0.2))
            face_core_y2 = min(h, int(fy + fh * 0.8))
            if face_core_x2 > face_core_x1 and face_core_y2 > face_core_y1:
                gc_mask[face_core_y1:face_core_y2, face_core_x1:face_core_x2] = cv2.GC_FGD

        if pose_landmarks and isinstance(pose_landmarks, list):
            # Connect torso keypoints (shoulders and hips) as definite foreground line
            for pt in pose_landmarks:
                px = int(pt.get("x", 0.0) * w)
                py = int(pt.get("y", 0.0) * h)
                vis = float(pt.get("visibility", 1.0))
                if 0 <= px < w and 0 <= py < h and vis > 0.5:
                    cv2.circle(gc_mask, (px, py), radius=max(3, int(w * 0.02)), color=cv2.GC_FGD, thickness=-1)

        # Allocate GrabCut GMM internal buffers
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)

        try:
            cv2.grabCut(
                bgr,
                gc_mask,
                None,
                bgd_model,
                fgd_model,
                iterCount=5,
                mode=cv2.GC_INIT_WITH_MASK,
            )
            # Binary mask: pixels marked GC_FGD or GC_PR_FGD
            raw_mask = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        except Exception as e:
            logger.warning(f"GrabCut iteration failed with mask init: {e}. Falling back to rectangular GrabCut.")
            rect = (roi_x1, roi_y1, max(10, roi_x2 - roi_x1), max(10, roi_y2 - roi_y1))
            gc_mask_rect = np.zeros((h, w), np.uint8)
            cv2.grabCut(
                bgr,
                gc_mask_rect,
                rect,
                bgd_model,
                fgd_model,
                iterCount=4,
                mode=cv2.GC_INIT_WITH_RECT,
            )
            raw_mask = np.where((gc_mask_rect == cv2.GC_FGD) | (gc_mask_rect == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

        # Apply Mask Refinement Pipeline
        refined_mask, quality_metrics = refine_mask(raw_mask, refinement_params)
        bbox = compute_mask_bounding_box(refined_mask)

        # Construct RGBA Foreground (original RGB + alpha channel)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgba = np.dstack((rgb, refined_mask))

        return SegmentationOutput(
            foreground_rgba=rgba,
            mask_alpha=refined_mask,
            bbox=bbox,
            quality_metrics=quality_metrics,
        )


# -----------------------------------------------------------------------------
# 4. Mock Segmentation Provider (For Testing & Simulation)
# -----------------------------------------------------------------------------

class MockSegmentationProvider(ForegroundSegmentationProvider):
    """
    Mock segmentation provider that generates deterministic, structured
    foreground/background layers for testing without external dependencies.
    """
    provider_name: str = "mock"
    model_name: str = "mock_matting_v1"

    def segment_foreground(
        self,
        image_np: np.ndarray,
        subject_guide: Optional[Dict[str, Any]] = None,
        refinement_params: Optional[Dict[str, Any]] = None,
    ) -> SegmentationOutput:
        h, w = image_np.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        # Draw an elliptical character silhouette in the center
        center_x = int(w * 0.5)
        center_y = int(h * 0.52)
        axes = (int(w * 0.28), int(h * 0.40))
        cv2.ellipse(mask, (center_x, center_y), axes, 0, 0, 360, 255, -1)

        # Add head circle
        head_center = (center_x, int(h * 0.24))
        head_radius = int(w * 0.16)
        cv2.circle(mask, head_center, head_radius, 255, -1)

        refined_mask, metrics = refine_mask(mask, refinement_params)
        bbox = compute_mask_bounding_box(refined_mask)

        rgb = image_np[:, :, :3] if image_np.shape[2] >= 3 else np.repeat(image_np[:, :, np.newaxis], 3, axis=2)
        rgba = np.dstack((rgb, refined_mask))

        return SegmentationOutput(
            foreground_rgba=rgba,
            mask_alpha=refined_mask,
            bbox=bbox,
            quality_metrics=metrics,
        )


# -----------------------------------------------------------------------------
# 5. Segmentation Provider Factory
# -----------------------------------------------------------------------------

def get_segmentation_provider(
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
) -> ForegroundSegmentationProvider:
    """
    Factory function returning the configured segmentation provider instance.
    """
    p_name = (provider_name or settings.SEGMENTATION_PROVIDER or "opencv_guided").strip().lower()

    if p_name in ("mock", "mock_matting", "test"):
        return MockSegmentationProvider()
    elif p_name in ("opencv", "opencv_guided", "grabcut", "default"):
        return OpenCVSubjectGuidedSegmentationProvider()
    else:
        logger.info(f"Requested segmentation provider '{p_name}' defaulting to OpenCV subject-guided provider.")
        return OpenCVSubjectGuidedSegmentationProvider()


# -----------------------------------------------------------------------------
# 6. Background Reconstruction & Dynamic Adaptation
# -----------------------------------------------------------------------------

def reconstruct_clean_background(
    source_image_rgb: np.ndarray,
    foreground_mask: np.ndarray,
    dilate_radius: int = 15,
) -> np.ndarray:
    """
    Reconstructs a clean background layer from the source scene by inpainting
    out the foreground character area.
    
    Prevents duplicate ghost copies of the subject in the background.
    """
    h, w = source_image_rgb.shape[:2]
    # Resize mask if dimensions differ from source image
    if foreground_mask.shape[:2] != (h, w):
        mask_resized = cv2.resize(foreground_mask, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        mask_resized = foreground_mask

    # Dilate mask to ensure entire character fringe is covered
    k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_radius, dilate_radius))
    dilated_mask = cv2.dilate(mask_resized, k_dilate, iterations=1)

    # Inpaint the character region using OpenCV Telea algorithm
    bgr = cv2.cvtColor(source_image_rgb, cv2.COLOR_RGB2BGR)
    inpainted_bgr = cv2.inpaint(bgr, dilated_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)
    inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)

    return inpainted_rgb


def apply_background_mode(
    background_rgb: np.ndarray,
    mode: str = "ORIGINAL",
) -> np.ndarray:
    """
    Applies controlled stylistic and atmospheric treatment to the background layer.
    
    Supported modes:
      - ORIGINAL: Preserves the source scene context cleanly.
      - SOFT_BLUR: Cinematic depth-of-field Gaussian blur (character pops in foreground).
      - DEPTH_STYLE: Dimensional depth with vignette gradient and contrast enhancement.
      - COMIC_STYLE: 3D Comic stylized background (bilateral smoothing, edge accentuation, vibrant palette).
    """
    clean_mode = (mode or "ORIGINAL").strip().upper()
    h, w = background_rgb.shape[:2]

    if clean_mode == "ORIGINAL":
        return background_rgb.copy()

    elif clean_mode == "SOFT_BLUR":
        # Cinematic shallow depth of field blur
        k_size = 31
        blurred = cv2.GaussianBlur(background_rgb, (k_size, k_size), sigmaX=14.0, sigmaY=14.0)
        return blurred

    elif clean_mode == "DEPTH_STYLE":
        # Depth blur + radial vignette gradient
        blurred = cv2.GaussianBlur(background_rgb, (21, 21), sigmaX=8.0, sigmaY=8.0)
        
        # Construct smooth radial vignette mask
        y, x = np.ogrid[:h, :w]
        cx, cy = w / 2.0, h / 2.0
        max_dist = np.sqrt(cx**2 + cy**2)
        dist_from_center = np.sqrt((x - cx)**2 + (y - cy)**2)
        vignette = 1.0 - np.clip((dist_from_center / max_dist) * 0.65, 0.0, 0.65)
        
        vignette_3c = np.repeat(vignette[:, :, np.newaxis], 3, axis=2)
        depth_styled = np.clip(blurred * vignette_3c * 1.05, 0, 255).astype(np.uint8)
        return depth_styled

    elif clean_mode == "COMIC_STYLE":
        # Bilateral filter for cel-shaded texture flattening while preserving major edges
        bgr = cv2.cvtColor(background_rgb, cv2.COLOR_RGB2BGR)
        bilateral = cv2.bilateralFilter(bgr, d=9, sigmaColor=75, sigmaSpace=75)

        # Subtle edge ink contours for 3D comic look
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, blockSize=9, C=2
        )
        edges_3c = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

        # Blend ink contours at 20% opacity
        comic_bgr = cv2.addWeighted(bilateral, 0.85, edges_3c, 0.15, 0)
        
        # Color saturation boost
        hsv = cv2.cvtColor(comic_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255)
        comic_saturated = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
        return comic_saturated

    else:
        logger.warning(f"Unknown background mode '{mode}'. Defaulting to ORIGINAL.")
        return background_rgb.copy()


def generate_composite_image(
    foreground_rgba: np.ndarray,
    background_rgb: np.ndarray,
) -> np.ndarray:
    """
    Composites the RGBA foreground cleanly over the treated RGB background layer
    using sub-pixel alpha blending.
    """
    h, w = foreground_rgba.shape[:2]
    # Ensure background matches foreground dimensions
    if background_rgb.shape[:2] != (h, w):
        bg_aligned = cv2.resize(background_rgb, (w, h), interpolation=cv2.INTER_LINEAR)
    else:
        bg_aligned = background_rgb

    fg_rgb = foreground_rgba[:, :, :3].astype(np.float32)
    alpha = (foreground_rgba[:, :, 3] / 255.0)[:, :, np.newaxis]
    bg_f = bg_aligned.astype(np.float32)

    composite = (fg_rgb * alpha + bg_f * (1.0 - alpha))
    return np.clip(composite, 0, 255).astype(np.uint8)


# -----------------------------------------------------------------------------
# 7. Pipeline Orchestrator
# -----------------------------------------------------------------------------

def run_segmentation_pipeline(
    db: Session,
    project_id: str,
    consistent_frame_id: Optional[str] = None,
    consistent_frame_ids: Optional[List[str]] = None,
    scene_id: Optional[str] = None,
    scene_ids: Optional[List[str]] = None,
    background_mode: str = "ORIGINAL",
    refinement_params: Optional[Dict[str, Any]] = None,
    force_regenerate: bool = False,
    provider_name: Optional[str] = None,
) -> List[SegmentationResult]:
    """
    Orchestrates the Phase 11 Foreground Segmentation & Dynamic Background pipeline.
    
    1. Validates project and targets.
    2. Identifies target consistent comic frames (Phase 10) or comic frames (Phase 9).
    3. Gathers Phase 8 face/pose guidance for the primary subject.
    4. Runs provider segmentation to extract foreground RGBA + refined alpha mask.
    5. Reconstructs clean background from source scene and applies requested background mode.
    6. Generates full composite preview.
    7. Atomically stores all 4 media assets and records SegmentationResult in SQLite DB.
    """
    clean_proj_id = project_id.strip()

    # 1. Validate project existence
    project = db.query(Project).filter(Project.id == clean_proj_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": f"Project '{clean_proj_id}' not found."},
        )

    # 2. Gather Phase 8 Vision Analysis for subject guidance
    vision_analysis = (
        db.query(VisionAnalysis)
        .filter(VisionAnalysis.project_id == clean_proj_id)
        .options(
            selectinload(VisionAnalysis.subjects).selectinload(DetectedSubject.face_detections),
            selectinload(VisionAnalysis.subjects).selectinload(DetectedSubject.pose_detections).selectinload(PoseDetection.landmarks),
        )
        .order_by(VisionAnalysis.created_at.desc())
        .first()
    )

    primary_subject = None
    if vision_analysis and vision_analysis.subjects:
        primary_subject = next((s for s in vision_analysis.subjects if s.is_primary), vision_analysis.subjects[0])

    # 3. Resolve Target Consistent Comic Frames
    target_frames: List[ConsistentComicFrame] = []
    
    query = (
        db.query(ConsistentComicFrame)
        .join(ConsistentComicFrame.generation)
        .filter(ConsistentComicFrame.generation.has(project_id=clean_proj_id))
        .options(
            selectinload(ConsistentComicFrame.output_media_file),
            selectinload(ConsistentComicFrame.scene).selectinload(VideoScene.keyframes),
        )
    )

    if consistent_frame_id:
        clean_fid = consistent_frame_id.strip()
        frame = query.filter(ConsistentComicFrame.id == clean_fid).first()
        if not frame:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "FRAME_NOT_FOUND", "message": f"Consistent frame '{clean_fid}' not found in project."},
            )
        target_frames = [frame]
    elif consistent_frame_ids:
        clean_fids = set(f.strip() for f in consistent_frame_ids if f.strip())
        target_frames = query.filter(ConsistentComicFrame.id.in_(clean_fids)).all()
        if not target_frames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_MATCHING_FRAMES", "message": "None of the requested consistent frame IDs were found."},
            )
    elif scene_id:
        clean_sid = scene_id.strip()
        target_frames = query.filter(ConsistentComicFrame.scene_id == clean_sid).all()
        if not target_frames:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NO_FRAMES_FOR_SCENE", "message": f"No consistent frames found for scene '{clean_sid}'."},
            )
    elif scene_ids:
        clean_sids = set(s.strip() for s in scene_ids if s.strip())
        target_frames = query.filter(ConsistentComicFrame.scene_id.in_(clean_sids)).all()
        if not target_frames:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NO_MATCHING_SCENES", "message": "No consistent frames found for the specified scenes."},
            )
    else:
        # Default: all consistent frames in project
        target_frames = query.order_by(ConsistentComicFrame.sequence.asc()).all()

    if not target_frames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MISSING_CONSISTENT_FRAMES",
                "message": "Phase 10 consistent comic frames must be generated before foreground segmentation.",
            },
        )

    # 4. Initialize Segmentation Provider
    provider = get_segmentation_provider(provider_name=provider_name)

    # 5. Prepare Storage Directories
    masks_dir = get_project_storage_dir(clean_proj_id, "segmentation_mask")
    fgs_dir = get_project_storage_dir(clean_proj_id, "segmentation_foreground")
    bgs_dir = get_project_storage_dir(clean_proj_id, "segmentation_background")
    comps_dir = get_project_storage_dir(clean_proj_id, "segmentation_composite")
    base_storage = get_base_storage_dir()

    results: List[SegmentationResult] = []

    for target_frame in target_frames:
        # Check existing result
        existing_result = (
            db.query(SegmentationResult)
            .filter(
                SegmentationResult.project_id == clean_proj_id,
                SegmentationResult.consistent_frame_id == target_frame.id,
            )
            .first()
        )

        if existing_result and not force_regenerate and existing_result.status == "completed" and existing_result.background_mode == background_mode.upper():
            logger.info(f"Reusing existing completed segmentation result '{existing_result.id}' for frame '{target_frame.id}'.")
            results.append(existing_result)
            continue

        # Locate consistent comic frame image on disk
        if not target_frame.output_media_file or not target_frame.output_media_file.file_path:
            logger.warning(f"Consistent frame '{target_frame.id}' has no associated output media file. Skipping.")
            continue

        frame_path = base_storage / target_frame.output_media_file.file_path
        if not frame_path.exists():
            logger.warning(f"Consistent frame file not found on disk at '{frame_path}'. Skipping.")
            continue

        try:
            # Read input comic frame image
            pil_img = Image.open(frame_path).convert("RGB")
            img_np = np.array(pil_img)
        except Exception as e:
            logger.error(f"Failed to read image file '{frame_path}': {e}")
            continue

        # Extract Subject Guide (face box & pose landmarks at frame timestamp)
        subject_guide = {}
        if primary_subject:
            # Match closest face detection
            if primary_subject.face_detections:
                closest_face = min(
                    primary_subject.face_detections,
                    key=lambda d: abs(d.timestamp - target_frame.timestamp),
                )
                subject_guide["face_bbox"] = {
                    "x": closest_face.x,
                    "y": closest_face.y,
                    "width": closest_face.width,
                    "height": closest_face.height,
                }
            # Match closest pose detection
            if primary_subject.pose_detections:
                closest_pose = min(
                    primary_subject.pose_detections,
                    key=lambda p: abs(p.timestamp - target_frame.timestamp),
                )
                if closest_pose.landmarks:
                    subject_guide["pose_landmarks"] = [
                        {"x": lm.x, "y": lm.y, "visibility": lm.visibility}
                        for lm in closest_pose.landmarks
                    ]

        # Locate Source Keyframe image for clean background reconstruction
        source_bg_rgb = img_np.copy()  # Fallback: comic frame itself
        source_keyframe_rec = None
        if target_frame.scene and target_frame.scene.keyframes:
            source_keyframe_rec = target_frame.scene.keyframes[0]
            if source_keyframe_rec.media_file_id:
                kf_media = db.query(MediaFile).filter(MediaFile.id == source_keyframe_rec.media_file_id).first()
                if kf_media and kf_media.file_path:
                    kf_path = base_storage / kf_media.file_path
                    if kf_path.exists():
                        try:
                            source_bg_rgb = np.array(Image.open(kf_path).convert("RGB"))
                        except Exception as e:
                            logger.warning(f"Could not load keyframe background '{kf_path}': {e}")

        # 6. Execute Segmentation
        seg_output = provider.segment_foreground(
            image_np=img_np,
            subject_guide=subject_guide,
            refinement_params=refinement_params,
        )

        # 7. Reconstruct Clean Background & Apply Mode
        reconstructed_bg = reconstruct_clean_background(
            source_image_rgb=source_bg_rgb,
            foreground_mask=seg_output.mask_alpha,
            dilate_radius=15,
        )
        styled_bg = apply_background_mode(
            background_rgb=reconstructed_bg,
            mode=background_mode,
        )

        # 8. Generate Composite Preview
        composite_rgb = generate_composite_image(
            foreground_rgba=seg_output.foreground_rgba,
            background_rgb=styled_bg,
        )

        # 9. Save Media Files to Disk
        result_id = existing_result.id if existing_result else str(uuid.uuid4())
        unique_token = uuid.uuid4().hex[:8]

        mask_filename = f"mask_{result_id}_{unique_token}.png"
        fg_filename = f"fg_{result_id}_{unique_token}.png"
        bg_filename = f"bg_{result_id}_{unique_token}.jpg"
        comp_filename = f"composite_{result_id}_{unique_token}.jpg"

        mask_path = masks_dir / mask_filename
        fg_path = fgs_dir / fg_filename
        bg_path = bgs_dir / bg_filename
        comp_path = comps_dir / comp_filename

        # Save Mask PNG
        Image.fromarray(seg_output.mask_alpha).save(mask_path, format="PNG")
        # Save Foreground RGBA PNG
        Image.fromarray(seg_output.foreground_rgba).save(fg_path, format="PNG")
        # Save Background JPEG
        Image.fromarray(styled_bg).save(bg_path, format="JPEG", quality=95)
        # Save Composite JPEG
        Image.fromarray(composite_rgb).save(comp_path, format="JPEG", quality=95)

        # Calculate file sizes and hashes
        def get_file_meta(p: Path) -> Tuple[int, str]:
            data = p.read_bytes()
            return len(data), hashlib.sha256(data).hexdigest()

        mask_size, mask_hash = get_file_meta(mask_path)
        fg_size, fg_hash = get_file_meta(fg_path)
        bg_size, bg_hash = get_file_meta(bg_path)
        comp_size, comp_hash = get_file_meta(comp_path)

        # 10. Register MediaFile records
        mask_media_id = str(uuid.uuid4())
        fg_media_id = str(uuid.uuid4())
        bg_media_id = str(uuid.uuid4())
        comp_media_id = str(uuid.uuid4())

        mask_media = MediaFile(
            id=mask_media_id,
            project_id=clean_proj_id,
            file_type="segmentation_mask",
            original_filename=f"mask_{target_frame.sequence}.png",
            stored_filename=mask_filename,
            file_path=str(mask_path.relative_to(base_storage)).replace("\\", "/"),
            mime_type="image/png",
            file_size=mask_size,
            sha256_hash=mask_hash,
        )

        fg_media = MediaFile(
            id=fg_media_id,
            project_id=clean_proj_id,
            file_type="segmentation_foreground",
            original_filename=f"foreground_{target_frame.sequence}.png",
            stored_filename=fg_filename,
            file_path=str(fg_path.relative_to(base_storage)).replace("\\", "/"),
            mime_type="image/png",
            file_size=fg_size,
            sha256_hash=fg_hash,
        )

        bg_media = MediaFile(
            id=bg_media_id,
            project_id=clean_proj_id,
            file_type="segmentation_background",
            original_filename=f"background_{target_frame.sequence}_{background_mode.lower()}.jpg",
            stored_filename=bg_filename,
            file_path=str(bg_path.relative_to(base_storage)).replace("\\", "/"),
            mime_type="image/jpeg",
            file_size=bg_size,
            sha256_hash=bg_hash,
        )

        comp_media = MediaFile(
            id=comp_media_id,
            project_id=clean_proj_id,
            file_type="segmentation_composite",
            original_filename=f"composite_{target_frame.sequence}_{background_mode.lower()}.jpg",
            stored_filename=comp_filename,
            file_path=str(comp_path.relative_to(base_storage)).replace("\\", "/"),
            mime_type="image/jpeg",
            file_size=comp_size,
            sha256_hash=comp_hash,
        )

        db.add_all([mask_media, fg_media, bg_media, comp_media])

        # 11. Create or Update SegmentationResult record
        if existing_result:
            seg_record = existing_result
            seg_record.provider = provider.provider_name
            seg_record.model = provider.model_name
            seg_record.status = "completed"
            seg_record.background_mode = background_mode.upper()
            seg_record.mask_media_file_id = mask_media_id
            seg_record.foreground_media_file_id = fg_media_id
            seg_record.background_media_file_id = bg_media_id
            seg_record.composite_media_file_id = comp_media_id
            seg_record.bbox_x = seg_output.bbox[0]
            seg_record.bbox_y = seg_output.bbox[1]
            seg_record.bbox_width = seg_output.bbox[2]
            seg_record.bbox_height = seg_output.bbox[3]
            seg_record.quality_metrics = seg_output.quality_metrics
            seg_record.updated_at = utc_now()
        else:
            seg_record = SegmentationResult(
                id=result_id,
                project_id=clean_proj_id,
                consistent_frame_id=target_frame.id,
                source_comic_frame_id=target_frame.source_comic_frame_id,
                source_scene_id=target_frame.scene_id,
                source_keyframe_id=source_keyframe_rec.id if source_keyframe_rec else None,
                provider=provider.provider_name,
                model=provider.model_name,
                status="completed",
                background_mode=background_mode.upper(),
                mask_media_file_id=mask_media_id,
                foreground_media_file_id=fg_media_id,
                background_media_file_id=bg_media_id,
                composite_media_file_id=comp_media_id,
                bbox_x=seg_output.bbox[0],
                bbox_y=seg_output.bbox[1],
                bbox_width=seg_output.bbox[2],
                bbox_height=seg_output.bbox[3],
                quality_metrics=seg_output.quality_metrics,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(seg_record)

        db.commit()
        db.refresh(seg_record)
        results.append(seg_record)

    logger.info(
        f"Completed segmentation pipeline for project '{clean_proj_id}': "
        f"{len(results)} layered scenes generated (Mode: {background_mode.upper()})."
    )

    return results
