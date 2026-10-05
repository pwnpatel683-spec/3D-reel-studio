"""
3D Reel Studio — Kinetic Lyrics & Text-Behind-Character Compositing Engine
Phase 12: Kinetic Lyrics + Text-Behind-Character Engine
"""

import io
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.config import settings
from app.core.logging import logger
from app.models.project import (
    LyricAnimation,
    LyricPreview,
    LyricSegment,
    LyricStyle,
    MediaFile,
    Project,
    SceneKeyframe,
    SegmentationResult,
    Transcript,
    TranscriptSegment,
    VideoScene,
    generate_uuid,
    utc_now,
)
from app.services.storage import get_project_storage_dir


# =====================================================================
# 1. DEFAULT PRESET DEFINITIONS
# =====================================================================

DEFAULT_LYRIC_STYLES: List[Dict[str, Any]] = [
    {
        "name": "STYLE_01_BOLD_CINEMATIC",
        "font_family": "Outfit",
        "font_size": 68,
        "font_weight": "bold",
        "fill_color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 5,
        "shadow_color": "rgba(0,0,0,0.85)",
        "shadow_offset_x": 4,
        "shadow_offset_y": 4,
        "shadow_blur": 8,
        "letter_spacing": 3,
        "line_spacing": 1.15,
        "text_transform": "uppercase",
        "alignment": "center",
    },
    {
        "name": "STYLE_02_MINIMAL_CLEAN",
        "font_family": "Outfit",
        "font_size": 54,
        "font_weight": "normal",
        "fill_color": "#F0F0F0",
        "outline_color": "#101216",
        "outline_width": 2,
        "shadow_color": "rgba(0,0,0,0.4)",
        "shadow_offset_x": 2,
        "shadow_offset_y": 2,
        "shadow_blur": 4,
        "letter_spacing": 2,
        "line_spacing": 1.2,
        "text_transform": "none",
        "alignment": "center",
    },
    {
        "name": "STYLE_03_COMIC_IMPACT",
        "font_family": "Outfit",
        "font_size": 76,
        "font_weight": "extra-bold",
        "fill_color": "#FFE600",
        "outline_color": "#0B0C10",
        "outline_width": 7,
        "shadow_color": "#FF2E63",
        "shadow_offset_x": 6,
        "shadow_offset_y": 6,
        "shadow_blur": 0,
        "letter_spacing": 4,
        "line_spacing": 1.1,
        "text_transform": "uppercase",
        "alignment": "center",
    },
    {
        "name": "STYLE_04_NEON_CYBER",
        "font_family": "JetBrains Mono",
        "font_size": 60,
        "font_weight": "bold",
        "fill_color": "#00FFF5",
        "outline_color": "#0B0C10",
        "outline_width": 4,
        "shadow_color": "rgba(255,46,99,0.9)",
        "shadow_offset_x": 0,
        "shadow_offset_y": 0,
        "shadow_blur": 16,
        "letter_spacing": 3,
        "line_spacing": 1.2,
        "text_transform": "uppercase",
        "alignment": "center",
    },
    {
        "name": "STYLE_05_DYNAMIC_OUTLINED",
        "font_family": "Outfit",
        "font_size": 72,
        "font_weight": "bold",
        "fill_color": "#FF2E63",
        "outline_color": "#FFFFFF",
        "outline_width": 4,
        "shadow_color": "rgba(0,0,0,0.75)",
        "shadow_offset_x": 4,
        "shadow_offset_y": 4,
        "shadow_blur": 8,
        "letter_spacing": 3,
        "line_spacing": 1.15,
        "text_transform": "uppercase",
        "alignment": "center",
    },
]

DEFAULT_LYRIC_ANIMATIONS: List[Dict[str, Any]] = [
    {"name": "POP", "animation_type": "POP", "duration": 0.35, "easing": "ease_out_back"},
    {"name": "SCALE_IN", "animation_type": "SCALE_IN", "duration": 0.40, "easing": "ease_out_cubic"},
    {"name": "FADE", "animation_type": "FADE", "duration": 0.30, "easing": "linear"},
    {"name": "SLIDE_UP", "animation_type": "SLIDE_UP", "duration": 0.35, "easing": "ease_out_cubic"},
    {"name": "SLIDE_LEFT", "animation_type": "SLIDE_LEFT", "duration": 0.35, "easing": "ease_out_cubic"},
    {"name": "SLIDE_RIGHT", "animation_type": "SLIDE_RIGHT", "duration": 0.35, "easing": "ease_out_cubic"},
    {"name": "BOUNCE", "animation_type": "BOUNCE", "duration": 0.50, "easing": "ease_out_bounce"},
    {"name": "WORD_BY_WORD", "animation_type": "WORD_BY_WORD", "duration": 0.25, "easing": "ease_out_cubic"},
]


# =====================================================================
# 2. EASING FUNCTIONS & ANIMATION STATE
# =====================================================================

@dataclass
class AnimationState:
    scale: float = 1.0
    opacity: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0
    active_word_index: Optional[int] = None
    progress: float = 1.0


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - math.pow(1.0 - t, 3)


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * math.pow(t - 1.0, 3) + c1 * math.pow(t - 1.0, 2)


def ease_out_bounce(t: float) -> float:
    t = max(0.0, min(1.0, t))
    n1 = 7.5625
    d1 = 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    elif t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def compute_animation_state(
    animation_type: str,
    progress: float,
    anim_duration: float = 0.35,
    segment_duration: float = 2.0,
    words_data: Optional[List[Dict[str, Any]]] = None,
    current_time: Optional[float] = None,
    start_time: float = 0.0,
) -> AnimationState:
    """
    Computes deterministic animation transformations based on progress [0.0, 1.0].
    """
    p = max(0.0, min(1.0, progress))
    anim_type = animation_type.upper().strip()

    # Fraction of segment duration allocated to intro transition
    intro_fraction = min(1.0, max(0.05, anim_duration / max(0.1, segment_duration)))
    intro_p = max(0.0, min(1.0, p / intro_fraction))

    state = AnimationState(progress=p)

    if anim_type == "FADE":
        state.opacity = ease_out_cubic(intro_p)
        state.scale = 1.0
        state.offset_x = 0.0
        state.offset_y = 0.0

    elif anim_type == "SCALE_IN":
        state.opacity = ease_out_cubic(intro_p)
        state.scale = 0.3 + 0.7 * ease_out_back(intro_p)
        state.offset_x = 0.0
        state.offset_y = 0.0

    elif anim_type == "POP":
        state.opacity = min(1.0, intro_p * 2.0)
        # Fast expansion to 1.18 then settle to 1.0
        if intro_p < 0.6:
            sub_p = intro_p / 0.6
            state.scale = 0.5 + 0.68 * ease_out_back(sub_p)
        else:
            sub_p = (intro_p - 0.6) / 0.4
            state.scale = 1.18 - 0.18 * ease_out_cubic(sub_p)

    elif anim_type == "SLIDE_UP":
        state.opacity = ease_out_cubic(intro_p)
        state.offset_y = 60.0 * (1.0 - ease_out_cubic(intro_p))
        state.scale = 1.0

    elif anim_type == "SLIDE_LEFT":
        state.opacity = ease_out_cubic(intro_p)
        state.offset_x = 100.0 * (1.0 - ease_out_cubic(intro_p))
        state.scale = 1.0

    elif anim_type == "SLIDE_RIGHT":
        state.opacity = ease_out_cubic(intro_p)
        state.offset_x = -100.0 * (1.0 - ease_out_cubic(intro_p))
        state.scale = 1.0

    elif anim_type == "BOUNCE":
        state.opacity = min(1.0, intro_p * 2.0)
        state.scale = 0.4 + 0.6 * ease_out_bounce(intro_p)
        state.offset_y = -30.0 * (1.0 - ease_out_bounce(intro_p))

    elif anim_type == "WORD_BY_WORD":
        state.opacity = 1.0
        state.scale = 1.0
        if words_data and current_time is not None:
            # Find active word index
            active_idx = 0
            for idx, w in enumerate(words_data):
                w_start = w.get("start", start_time)
                if current_time >= w_start:
                    active_idx = idx
            state.active_word_index = active_idx
        elif words_data:
            # Progress based index
            num_words = max(1, len(words_data))
            state.active_word_index = min(num_words - 1, int(p * num_words))

    else:
        # Default neutral
        state.opacity = 1.0
        state.scale = 1.0

    return state


# =====================================================================
# 3. COLOR & FONT HELPERS
# =====================================================================

def parse_color_tuple(color_str: Optional[str], default: Tuple[int, int, int, int] = (255, 255, 255, 255)) -> Tuple[int, int, int, int]:
    """
    Parses hex (#RRGGBB, #RRGGBBAA) or rgba(r,g,b,a) string into (R, G, B, A) tuple.
    """
    if not color_str:
        return default
    c = color_str.strip()
    if c.startswith("#"):
        c = c[1:]
        if len(c) == 6:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            return (r, g, b, 255)
        elif len(c) == 8:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            a = int(c[6:8], 16)
            return (r, g, b, a)
    elif c.lower().startswith("rgba"):
        try:
            parts = c.replace("rgba(", "").replace(")", "").split(",")
            r = int(parts[0].strip())
            g = int(parts[1].strip())
            b = int(parts[2].strip())
            a_val = float(parts[3].strip())
            a = int(a_val * 255) if a_val <= 1.0 else int(a_val)
            return (r, g, b, max(0, min(255, a)))
        except Exception:
            return default
    elif c.lower().startswith("rgb"):
        try:
            parts = c.replace("rgb(", "").replace(")", "").split(",")
            r = int(parts[0].strip())
            g = int(parts[1].strip())
            b = int(parts[2].strip())
            return (r, g, b, 255)
        except Exception:
            return default
    return default


_FONT_CACHE: Dict[Tuple[str, int, str], ImageFont.ImageFont] = {}


def get_pil_font(font_family: str = "Outfit", font_size: int = 64, font_weight: str = "bold") -> ImageFont.ImageFont:
    """
    Safely retrieves a TrueType font, trying bundled/system paths with a guaranteed fallback.
    """
    cache_key = (font_family.lower(), font_size, font_weight.lower())
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    is_bold = "bold" in font_weight.lower() or "extra" in font_weight.lower()

    # Search candidates across OS
    candidates = []
    if "mono" in font_family.lower() or "jetbrains" in font_family.lower():
        candidates.extend([
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/consolab.ttf" if is_bold else "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if is_bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ])
    elif "impact" in font_family.lower() or "comic" in font_family.lower():
        candidates.extend([
            "C:/Windows/Fonts/impact.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    else:
        # Modern Sans (Outfit / Arial / Segoe UI)
        if is_bold:
            candidates.extend([
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/calibrib.ttf",
                "C:/Windows/Fonts/tahomabd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ])
        else:
            candidates.extend([
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/calibri.ttf",
                "C:/Windows/Fonts/tahoma.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ])

    for font_path in candidates:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
                _FONT_CACHE[cache_key] = font
                return font
            except Exception:
                pass

    # Generic TrueType fallback
    for fallback_name in ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]:
        try:
            font = ImageFont.truetype(fallback_name, font_size)
            _FONT_CACHE[cache_key] = font
            return font
        except Exception:
            pass

    # Guaranteed Pillow default font
    default_font = ImageFont.load_default()
    _FONT_CACHE[cache_key] = default_font
    return default_font


# =====================================================================
# 4. TEXT LAYOUT & WRAPPING
# =====================================================================

def wrap_text_lines(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    text_transform: str = "uppercase",
) -> List[str]:
    """
    Wraps text into lines that fit within max_width pixels.
    """
    raw_text = text.strip()
    if text_transform == "uppercase":
        raw_text = raw_text.upper()
    elif text_transform == "lowercase":
        raw_text = raw_text.lower()

    if not raw_text:
        return [""]

    # If explicit newlines exist, respect them
    paragraphs = raw_text.split("\n")
    lines: List[str] = []

    for para in paragraphs:
        words = para.split()
        if not words:
            continue

        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            # Measure width
            try:
                bbox = font.getbbox(test_line)
                line_w = bbox[2] - bbox[0]
            except Exception:
                line_w = len(test_line) * 20

            if line_w <= max_width or not current_line:
                current_line.append(word)
            else:
                lines.append(" ".join(current_line))
                current_line = [word]

        if current_line:
            lines.append(" ".join(current_line))

    return lines if lines else [raw_text]


# =====================================================================
# 5. KINETIC TEXT RENDERING ENGINE
# =====================================================================

class KineticTextEngine:
    """
    Renders kinetic typography to a transparent RGBA layer with styling, outlines, shadows, and motion transforms.
    """

    @staticmethod
    def render_text_layer(
        text: str,
        canvas_width: int,
        canvas_height: int,
        style: LyricStyle,
        anim_state: AnimationState,
        pos_x: float = 0.5,
        pos_y: float = 0.75,
        scale_override: float = 1.0,
        rotation_override: float = 0.0,
        opacity_override: float = 1.0,
    ) -> Image.Image:
        """
        Generates a transparent RGBA PIL Image with stylized kinetic typography.
        """
        # Canvas RGBA
        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))

        if not text or not text.strip():
            return canvas

        font_size = max(16, int(style.font_size * scale_override * anim_state.scale))
        font = get_pil_font(style.font_family, font_size, style.font_weight)

        max_text_width = int(canvas_width * 0.85)  # 85% safe margin
        lines = wrap_text_lines(text, font, max_text_width, style.text_transform)

        # Measure multiline text bounds
        line_heights = []
        line_widths = []
        for line in lines:
            try:
                bbox = font.getbbox(line)
                lw = bbox[2] - bbox[0]
                lh = bbox[3] - bbox[1]
            except Exception:
                lw = len(line) * font_size * 0.6
                lh = font_size
            line_widths.append(lw)
            line_heights.append(lh)

        line_spacing = style.line_spacing or 1.15
        total_text_height = sum(line_heights) + int((len(lines) - 1) * font_size * (line_spacing - 1.0))
        max_line_width = max(line_widths) if line_widths else max_text_width

        # Extra buffer padding for stroke and shadow blur
        padding = max(32, int(style.shadow_blur * 2 + style.outline_width * 4 + 20))
        temp_w = int(max_line_width + padding * 2)
        temp_h = int(total_text_height + padding * 2)

        # Temporary drawing surface for the text block
        text_surface = Image.new("RGBA", (temp_w, temp_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_surface)

        fill_rgba = parse_color_tuple(style.fill_color, (255, 255, 255, 255))
        outline_rgba = parse_color_tuple(style.outline_color, (0, 0, 0, 255)) if style.outline_width > 0 else None
        shadow_rgba = parse_color_tuple(style.shadow_color, (0, 0, 0, 180))

        # 1. Draw Shadow Pass if configured
        if style.shadow_color and (style.shadow_offset_x != 0 or style.shadow_offset_y != 0 or style.shadow_blur > 0):
            shadow_surface = Image.new("RGBA", (temp_w, temp_h), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_surface)
            curr_y = padding + style.shadow_offset_y

            for i, line in enumerate(lines):
                lw = line_widths[i]
                if style.alignment == "left":
                    curr_x = padding + style.shadow_offset_x
                elif style.alignment == "right":
                    curr_x = padding + style.shadow_offset_x + (max_line_width - lw)
                else:  # center
                    curr_x = padding + style.shadow_offset_x + (max_line_width - lw) / 2.0

                shadow_draw.text(
                    (curr_x, curr_y),
                    line,
                    font=font,
                    fill=shadow_rgba,
                    stroke_width=int(style.outline_width),
                    stroke_fill=shadow_rgba,
                )
                curr_y += line_heights[i] + int(font_size * (line_spacing - 1.0))

            if style.shadow_blur > 0:
                shadow_surface = shadow_surface.filter(ImageFilter.GaussianBlur(radius=style.shadow_blur / 2.0))

            text_surface.alpha_composite(shadow_surface)

        # 2. Draw Text with Outline/Stroke and Fill
        curr_y = padding
        for i, line in enumerate(lines):
            lw = line_widths[i]
            if style.alignment == "left":
                curr_x = padding
            elif style.alignment == "right":
                curr_x = padding + (max_line_width - lw)
            else:  # center
                curr_x = padding + (max_line_width - lw) / 2.0

            draw.text(
                (curr_x, curr_y),
                line,
                font=font,
                fill=fill_rgba,
                stroke_width=int(style.outline_width) if outline_rgba else 0,
                stroke_fill=outline_rgba if outline_rgba else None,
            )
            curr_y += line_heights[i] + int(font_size * (line_spacing - 1.0))

        # 3. Apply Rotation if specified
        total_rot = rotation_override + anim_state.rotation
        if abs(total_rot) > 0.1:
            text_surface = text_surface.rotate(total_rot, resample=Image.BICUBIC, expand=True)
            temp_w, temp_h = text_surface.size

        # 4. Global Opacity Modulation
        final_alpha = max(0.0, min(1.0, opacity_override * anim_state.opacity))
        if final_alpha < 0.999:
            # Scale alpha channel
            r, g, b, a = text_surface.split()
            a = a.point(lambda p: int(p * final_alpha))
            text_surface = Image.merge("RGBA", (r, g, b, a))

        # 5. Position on Canvas
        target_center_x = pos_x * canvas_width + anim_state.offset_x
        target_center_y = pos_y * canvas_height + anim_state.offset_y

        paste_x = int(target_center_x - temp_w / 2.0)
        paste_y = int(target_center_y - temp_h / 2.0)

        # Composite text surface onto master canvas
        canvas.paste(text_surface, (paste_x, paste_y), text_surface)
        return canvas


# =====================================================================
# 6. TEXT-BEHIND-CHARACTER COMPOSITOR
# =====================================================================

def composite_text_behind_character(
    bg_image: Image.Image,
    text_layer: Image.Image,
    fg_image: Image.Image,
    alpha_mask: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Composites 3 layers in exact Z-order:
      Layer 0 (Bottom): Background Scene (RGB)
      Layer 1 (Middle): Kinetic Text Layer (RGBA)
      Layer 2 (Top):    Character Foreground (RGBA / Masked)

    The character foreground naturally occludes the kinetic text, producing the text-behind-character visual effect!
    """
    target_size = bg_image.size
    bg = bg_image.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)
    text = text_layer.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)
    fg = fg_image.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)

    # 1. Composite Text over Background
    bg_with_text = Image.alpha_composite(bg, text)

    # 2. Composite Character Foreground over (Background + Text)
    if alpha_mask is not None:
        mask = alpha_mask.convert("L").resize(target_size, Image.Resampling.LANCZOS)
        # Apply mask to FG alpha
        fg_r, fg_g, fg_b, _ = fg.split()
        fg = Image.merge("RGBA", (fg_r, fg_g, fg_b, mask))

    final_composite = Image.alpha_composite(bg_with_text, fg)
    return final_composite.convert("RGB")


# =====================================================================
# 7. SERVICE & DATABASE SYNC ORCHESTRATION
# =====================================================================

def get_or_create_default_styles(db: Session, project_id: str) -> List[LyricStyle]:
    """Ensures default lyric styles exist for the project."""
    existing = db.query(LyricStyle).filter(LyricStyle.project_id == project_id).all()
    if existing:
        return existing

    styles = []
    for s_def in DEFAULT_LYRIC_STYLES:
        style = LyricStyle(
            id=f"style-{generate_uuid()}",
            project_id=project_id,
            name=s_def["name"],
            font_family=s_def["font_family"],
            font_size=s_def["font_size"],
            font_weight=s_def["font_weight"],
            fill_color=s_def["fill_color"],
            outline_color=s_def["outline_color"],
            outline_width=s_def["outline_width"],
            shadow_color=s_def["shadow_color"],
            shadow_offset_x=s_def["shadow_offset_x"],
            shadow_offset_y=s_def["shadow_offset_y"],
            shadow_blur=s_def["shadow_blur"],
            letter_spacing=s_def["letter_spacing"],
            line_spacing=s_def["line_spacing"],
            text_transform=s_def["text_transform"],
            alignment=s_def["alignment"],
        )
        db.add(style)
        styles.append(style)

    db.commit()
    for s in styles:
        db.refresh(s)
    return styles


def get_or_create_default_animations(db: Session, project_id: str) -> List[LyricAnimation]:
    """Ensures default lyric animations exist for the project."""
    existing = db.query(LyricAnimation).filter(LyricAnimation.project_id == project_id).all()
    if existing:
        return existing

    anims = []
    for a_def in DEFAULT_LYRIC_ANIMATIONS:
        anim = LyricAnimation(
            id=f"anim-{generate_uuid()}",
            project_id=project_id,
            name=a_def["name"],
            animation_type=a_def["animation_type"],
            duration=a_def["duration"],
            easing=a_def["easing"],
        )
        db.add(anim)
        anims.append(anim)

    db.commit()
    for a in anims:
        db.refresh(a)
    return anims


def sync_transcript_to_lyrics(
    db: Session,
    project_id: str,
    force_recreate: bool = False,
    default_style_name: Optional[str] = None,
    default_animation_name: Optional[str] = None,
) -> Tuple[List[LyricSegment], List[LyricStyle], List[LyricAnimation]]:
    """
    Synchronizes Phase 6 TranscriptSegments into editable LyricSegments.
    """
    styles = get_or_create_default_styles(db, project_id)
    animations = get_or_create_default_animations(db, project_id)

    # Pick default style & animation
    target_style = next((s for s in styles if s.name == default_style_name), styles[0] if styles else None)
    target_anim = next((a for a in animations if a.name == default_animation_name), animations[0] if animations else None)

    existing_segments = (
        db.query(LyricSegment)
        .filter(LyricSegment.project_id == project_id)
        .order_by(LyricSegment.sequence)
        .all()
    )

    if existing_segments and not force_recreate:
        return existing_segments, styles, animations

    if force_recreate and existing_segments:
        for seg in existing_segments:
            db.delete(seg)
        db.commit()

    # Load latest transcript for project
    transcript = (
        db.query(Transcript)
        .filter(Transcript.project_id == project_id)
        .order_by(desc(Transcript.created_at))
        .first()
    )

    if not transcript or not transcript.segments:
        logger.warning(f"No transcript segments found for project {project_id} during lyric sync.")
        return [], styles, animations

    created_segments: List[LyricSegment] = []
    for t_seg in transcript.segments:
        l_seg = LyricSegment(
            id=f"lyric-seg-{generate_uuid()}",
            project_id=project_id,
            transcript_segment_id=t_seg.id,
            style_id=target_style.id if target_style else None,
            animation_id=target_anim.id if target_anim else None,
            sequence=t_seg.sequence,
            start_time=t_seg.start_time,
            end_time=t_seg.end_time,
            text=t_seg.text,
            position_x=0.5,
            position_y=0.75,  # Lower center behind subject chest/torso
            scale=1.0,
            rotation=0.0,
            opacity=1.0,
            z_layer=1,  # 1 = text behind character
            enabled=True,
            words_data=t_seg.words_data,
        )
        db.add(l_seg)
        created_segments.append(l_seg)

    db.commit()
    for s in created_segments:
        db.refresh(s)

    logger.info(f"Successfully synced {len(created_segments)} lyric segments for project {project_id}.")
    return created_segments, styles, animations


def generate_lyric_preview(
    db: Session,
    project_id: str,
    scene_id: Optional[str] = None,
    segmentation_id: Optional[str] = None,
    lyric_segment_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    text_override: Optional[str] = None,
    position_x: Optional[float] = None,
    position_y: Optional[float] = None,
    scale: Optional[float] = None,
    opacity: Optional[float] = None,
    style_id: Optional[str] = None,
    animation_id: Optional[str] = None,
) -> LyricPreview:
    """
    Renders and stores a text-behind-character composite preview frame.
    """
    # 1. Resolve Segmentation Result (Layer 0 Background and Layer 2 Foreground)
    seg_query = db.query(SegmentationResult).filter(SegmentationResult.project_id == project_id)
    if segmentation_id:
        seg_result = seg_query.filter(SegmentationResult.id == segmentation_id).first()
    elif scene_id:
        seg_result = seg_query.filter(SegmentationResult.source_scene_id == scene_id).first()
    else:
        seg_result = seg_query.order_by(desc(SegmentationResult.created_at)).first()

    if not seg_result:
        raise ValueError("No segmentation result available for text-behind-character compositing. Please run Phase 11 segmentation first.")

    # 2. Resolve Lyric Segment
    lyric_query = db.query(LyricSegment).filter(LyricSegment.project_id == project_id)
    if lyric_segment_id:
        lyric_seg = lyric_query.filter(LyricSegment.id == lyric_segment_id).first()
    elif timestamp is not None:
        lyric_seg = lyric_query.filter(LyricSegment.start_time <= timestamp, LyricSegment.end_time >= timestamp).first()
        if not lyric_seg:
            lyric_seg = lyric_query.order_by(LyricSegment.sequence).first()
    else:
        lyric_seg = lyric_query.order_by(LyricSegment.sequence).first()

    # 3. Resolve Style and Animation
    styles = get_or_create_default_styles(db, project_id)
    animations = get_or_create_default_animations(db, project_id)

    chosen_style = None
    if style_id:
        chosen_style = db.query(LyricStyle).filter(LyricStyle.id == style_id, LyricStyle.project_id == project_id).first()
    if not chosen_style and lyric_seg and lyric_seg.style_id:
        chosen_style = db.query(LyricStyle).filter(LyricStyle.id == lyric_seg.style_id).first()
    if not chosen_style:
        chosen_style = styles[0]

    chosen_anim = None
    if animation_id:
        chosen_anim = db.query(LyricAnimation).filter(LyricAnimation.id == animation_id, LyricAnimation.project_id == project_id).first()
    if not chosen_anim and lyric_seg and lyric_seg.animation_id:
        chosen_anim = db.query(LyricAnimation).filter(LyricAnimation.id == lyric_seg.animation_id).first()
    if not chosen_anim:
        chosen_anim = animations[0]

    # 4. Load Physical Layer Assets
    bg_media = seg_result.background_media
    fg_media = seg_result.foreground_media
    mask_media = seg_result.mask_media

    if not bg_media or not os.path.exists(bg_media.file_path):
        raise ValueError(f"Background layer media not found on disk for segmentation {seg_result.id}")
    if not fg_media or not os.path.exists(fg_media.file_path):
        raise ValueError(f"Foreground layer media not found on disk for segmentation {seg_result.id}")

    bg_img = Image.open(bg_media.file_path)
    fg_img = Image.open(fg_media.file_path)
    mask_img = Image.open(mask_media.file_path) if (mask_media and os.path.exists(mask_media.file_path)) else None

    W, H = bg_img.size

    # 5. Compute Text & Timing
    display_text = text_override if text_override is not None else (lyric_seg.text if lyric_seg else "3D REEL STUDIO")
    effective_pos_x = position_x if position_x is not None else (lyric_seg.position_x if lyric_seg else 0.5)
    effective_pos_y = position_y if position_y is not None else (lyric_seg.position_y if lyric_seg else 0.75)
    effective_scale = scale if scale is not None else (lyric_seg.scale if lyric_seg else 1.0)
    effective_opacity = opacity if opacity is not None else (lyric_seg.opacity if lyric_seg else 1.0)

    # Animation progress
    if lyric_seg and timestamp is not None and lyric_seg.end_time > lyric_seg.start_time:
        raw_p = (timestamp - lyric_seg.start_time) / (lyric_seg.end_time - lyric_seg.start_time)
        progress = max(0.0, min(1.0, raw_p))
    else:
        progress = 1.0

    words_list = None
    if lyric_seg and lyric_seg.words_data:
        try:
            words_list = json.loads(lyric_seg.words_data)
        except Exception:
            pass

    anim_state = compute_animation_state(
        animation_type=chosen_anim.animation_type if chosen_anim else "POP",
        progress=progress,
        anim_duration=chosen_anim.duration if chosen_anim else 0.35,
        segment_duration=(lyric_seg.end_time - lyric_seg.start_time) if lyric_seg else 2.0,
        words_data=words_list,
        current_time=timestamp,
        start_time=lyric_seg.start_time if lyric_seg else 0.0,
    )

    # 6. Render Kinetic Text Layer (Layer 1)
    text_layer = KineticTextEngine.render_text_layer(
        text=display_text,
        canvas_width=W,
        canvas_height=H,
        style=chosen_style,
        anim_state=anim_state,
        pos_x=effective_pos_x,
        pos_y=effective_pos_y,
        scale_override=effective_scale,
        opacity_override=effective_opacity,
    )

    # 7. Composite Text Behind Character (Layer 0 + Layer 1 + Layer 2)
    composite_img = composite_text_behind_character(
        bg_image=bg_img,
        text_layer=text_layer,
        fg_image=fg_img,
        alpha_mask=mask_img,
    )

    # 8. Persist Rendered Preview Asset
    storage_dir = get_project_storage_dir(project_id, "lyrics_preview")
    preview_filename = f"preview_{generate_uuid()}.png"
    preview_path = storage_dir / preview_filename
    composite_img.save(preview_path, format="PNG", optimize=True)

    file_size = preview_path.stat().st_size

    # Record MediaFile
    preview_media = MediaFile(
        id=f"media-lyric-prev-{generate_uuid()}",
        project_id=project_id,
        file_type="lyrics_preview",
        original_filename=preview_filename,
        stored_filename=preview_filename,
        file_path=str(preview_path),
        mime_type="image/png",
        file_size=file_size,
    )
    db.add(preview_media)

    # Record LyricPreview
    preview_record = LyricPreview(
        id=f"prev-{generate_uuid()}",
        project_id=project_id,
        lyric_segment_id=lyric_seg.id if lyric_seg else None,
        scene_id=seg_result.source_scene_id,
        segmentation_id=seg_result.id,
        timestamp=timestamp if timestamp is not None else (lyric_seg.start_time if lyric_seg else 0.0),
        output_media_file_id=preview_media.id,
        compositing_metadata={
            "text": display_text,
            "style_name": chosen_style.name,
            "animation_type": chosen_anim.animation_type if chosen_anim else "POP",
            "position": {"x": effective_pos_x, "y": effective_pos_y},
            "scale": effective_scale,
            "opacity": effective_opacity,
            "progress": progress,
            "layer_order": ["background", "kinetic_text", "foreground_character"],
        },
    )
    db.add(preview_record)
    db.commit()
    db.refresh(preview_record)

    logger.info(f"Generated text-behind-character lyric preview {preview_record.id} for project {project_id}.")
    return preview_record
