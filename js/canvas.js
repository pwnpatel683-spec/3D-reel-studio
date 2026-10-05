/**
 * ===================================================================
 * 3D REEL STUDIO — Canvas Typography Foundation
 * Phase 1 Frontend Foundation
 * ===================================================================
 * 
 * NOTE FOR FUTURE PHASES:
 * This module provides the high-performance 2D Canvas typography rendering foundation.
 * Phase 15 will implement the full synchronized Kinetic Lyrics Engine with:
 * - Word-level Whisper timestamps
 * - Kinetic pop/bounce springs
 * - Sound-reactive audio waveform pulses
 * - Comic book halftone & sound effect banners (POW, BAM, WOOSH)
 * 
 * In Phase 1, we implement the core canvas geometry, resizing engine, and 
 * parameterized drawKineticText() system.
 */

class KineticCanvasEngine {
  constructor(canvasElement, videoElement) {
    this.canvas = canvasElement;
    this.ctx = canvasElement.getContext('2d');
    this.video = videoElement;
    this.dpr = window.devicePixelRatio || 1;
    this.width = 0;
    this.height = 0;
    this.demoActive = false;
    this.demoAnimationFrame = null;

    this.init();
  }

  /**
   * Initialize canvas listeners and resize observer
   */
  init() {
    this.resizeCanvas();
    window.addEventListener('resize', () => this.resizeCanvas());

    if (window.ResizeObserver && this.canvas.parentElement) {
      const ro = new ResizeObserver(() => this.resizeCanvas());
      ro.observe(this.canvas.parentElement);
    }
  }

  /**
   * Resize canvas matching the video container's exact bounding box with high-DPI crispness
   */
  resizeCanvas() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    this.width = rect.width;
    this.height = rect.height;

    // Set internal render resolution accounting for device pixel ratio
    this.canvas.width = Math.floor(rect.width * this.dpr);
    this.canvas.height = Math.floor(rect.height * this.dpr);

    // Normalize coordinates so 1 canvas unit = 1 CSS pixel
    this.ctx.scale(this.dpr, this.dpr);

    if (this.demoActive) {
      this.renderSampleKineticFrame();
    }
  }

  /**
   * Clears the entire canvas viewport
   */
  clearCanvas() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, this.width, this.height);
  }

  /**
   * Renders a customizable, stylized kinetic text element
   * @param {string} text - The text string to render
   * @param {Object} options - Typography styling and transformation options
   */
  drawKineticText(text, options = {}) {
    if (!this.ctx || !text) return;

    const {
      fontFamily = "'Outfit', 'Impact', sans-serif",
      fontSize = 32,
      fontWeight = '800',
      align = 'center',           // 'left' | 'center' | 'right'
      baseline = 'middle',        // 'top' | 'middle' | 'bottom'
      position = 'bottom',        // 'top' | 'center' | 'bottom' | 'custom'
      customX = null,
      customY = null,
      fillGradient = true,
      gradientColors = ['#ff2e63', '#00fff5'], // Neon Red to Cyber Cyan
      fillColor = '#ffffff',
      stroke = true,
      strokeColor = '#0b0c10',
      strokeWidth = 6,
      shadow = true,
      shadowColor = 'rgba(0, 255, 245, 0.4)',
      shadowBlur = 15,
      shadowOffsetX = 0,
      shadowOffsetY = 4,
      scale = 1.0,
      rotation = 0,               // In degrees
      opacity = 1.0,
      letterSpacing = 2           // Pixel letter spacing
    } = options;

    const ctx = this.ctx;
    ctx.save();

    // 1. Calculate base coordinates
    let targetX = this.width / 2;
    let targetY = this.height * 0.82; // Default bottom third safe zone

    if (position === 'top') {
      targetY = this.height * 0.18;
    } else if (position === 'center') {
      targetY = this.height / 2;
    } else if (position === 'custom' && customX !== null && customY !== null) {
      targetX = customX;
      targetY = customY;
    }

    // 2. Apply Alpha & Global Transform
    ctx.globalAlpha = Math.max(0, Math.min(1, opacity));
    ctx.translate(targetX, targetY);

    if (rotation !== 0) {
      ctx.rotate((rotation * Math.PI) / 180);
    }

    if (scale !== 1.0) {
      ctx.scale(scale, scale);
    }

    // 3. Configure Typography
    ctx.font = `${fontWeight} ${fontSize}px ${fontFamily}`;
    ctx.textAlign = align;
    ctx.textBaseline = baseline;

    // 4. Configure Glow & Shadow
    if (shadow) {
      ctx.shadowColor = shadowColor;
      ctx.shadowBlur = shadowBlur;
      ctx.shadowOffsetX = shadowOffsetX;
      ctx.shadowOffsetY = shadowOffsetY;
    } else {
      ctx.shadowColor = 'transparent';
    }

    // 5. Build Gradient Fill if enabled
    let currentFillStyle = fillColor;
    if (fillGradient && gradientColors.length >= 2) {
      const gradient = ctx.createLinearGradient(
        -this.width / 4, 
        -fontSize, 
        this.width / 4, 
        fontSize
      );
      gradient.addColorStop(0, gradientColors[0]);
      gradient.addColorStop(1, gradientColors[1]);
      currentFillStyle = gradient;
    }

    // 6. Draw Outline / Stroke
    if (stroke && strokeWidth > 0) {
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = strokeWidth;
      ctx.lineJoin = 'miter';
      ctx.miterLimit = 2;
      ctx.strokeText(text.toUpperCase(), 0, 0);
    }

    // 7. Draw Core Fill
    ctx.fillStyle = currentFillStyle;
    ctx.fillText(text.toUpperCase(), 0, 0);

    ctx.restore();
  }

  /**
   * Sample demonstration frame showing kinetic typography system in action
   */
  renderSampleKineticFrame(timestamp = 0) {
    this.clearCanvas();

    const time = timestamp * 0.003;
    const pulseScale = 1.0 + Math.sin(time * 3) * 0.06;
    const tiltRot = Math.cos(time * 2) * 3;

    // Top Brand Tag
    this.drawKineticText("◈ 3D COMIC REEL", {
      fontSize: 16,
      position: 'top',
      fillGradient: false,
      fillColor: '#00fff5',
      strokeWidth: 3,
      shadowBlur: 10,
      shadowColor: 'rgba(0, 255, 245, 0.6)'
    });

    // Main Kinetic Lyric Pop (Phase 15 Engine preview)
    this.drawKineticText("CYBERPUNK BEAT", {
      fontSize: 32,
      position: 'center',
      scale: pulseScale,
      rotation: tiltRot,
      gradientColors: ['#ff2e63', '#00fff5'],
      strokeWidth: 8,
      shadowBlur: 20,
      shadowColor: 'rgba(255, 46, 99, 0.6)'
    });

    // Subtitle Line
    this.drawKineticText("AI SYNCHRONIZED REEL", {
      fontSize: 14,
      position: 'bottom',
      fillGradient: false,
      fillColor: '#f0f3f8',
      strokeWidth: 4,
      shadowBlur: 8,
      shadowColor: 'rgba(0, 255, 245, 0.4)'
    });
  }

  /**
   * Toggle the interactive typography preview animation loop
   */
  toggleDemoMode() {
    this.demoActive = !this.demoActive;
    if (this.demoActive) {
      const animate = (timestamp) => {
        if (!this.demoActive) return;
        this.renderSampleKineticFrame(timestamp);
        this.demoAnimationFrame = requestAnimationFrame(animate);
      };
      this.demoAnimationFrame = requestAnimationFrame(animate);
    } else {
      if (this.demoAnimationFrame) {
        cancelAnimationFrame(this.demoAnimationFrame);
      }
      this.clearCanvas();
    }
    return this.demoActive;
  }

  /**
   * Renders computer vision face bounding boxes and 17-point pose skeleton overlays
   * @param {Object} visionAnalysis 
   * @param {number} currentTime 
   */
  drawVisionOverlays(visionAnalysis, currentTime = 0.0) {
    if (!this.ctx || !visionAnalysis || !visionAnalysis.subjects) return;
    if (this.demoActive) return;

    const showFace = appState.visionOverlays?.showFaceBox ?? true;
    const showPose = appState.visionOverlays?.showPoseSkeleton ?? true;
    if (!showFace && !showPose) {
      this.clearCanvas();
      return;
    }

    this.clearCanvas();

    const w = this.width;
    const h = this.height;
    if (w === 0 || h === 0) return;

    // Find primary subject
    const subjects = visionAnalysis.subjects || [];
    const primary = subjects.find(s => s.is_primary) || subjects[0];
    if (!primary) return;

    // Find closest face detection to currentTime
    let closestFace = null;
    let minFaceDiff = Infinity;
    (primary.face_detections || []).forEach(f => {
      const diff = Math.abs(f.timestamp - currentTime);
      if (diff < minFaceDiff) {
        minFaceDiff = diff;
        closestFace = f;
      }
    });

    // Find closest pose detection to currentTime
    let closestPose = null;
    let minPoseDiff = Infinity;
    (primary.pose_detections || []).forEach(p => {
      const diff = Math.abs(p.timestamp - currentTime);
      if (diff < minPoseDiff) {
        minPoseDiff = diff;
        closestPose = p;
      }
    });

    // 1. Draw Face Bounding Box & Corner Brackets
    if (showFace && closestFace) {
      const fx = closestFace.x * w;
      const fy = closestFace.y * h;
      const fw = closestFace.width * w;
      const fh = closestFace.height * h;

      this.ctx.save();
      this.ctx.strokeStyle = 'rgba(0, 255, 245, 0.85)';
      this.ctx.lineWidth = 2;
      this.ctx.fillStyle = 'rgba(0, 255, 245, 0.08)';

      // Box fill and border
      this.ctx.fillRect(fx, fy, fw, fh);
      this.ctx.strokeRect(fx, fy, fw, fh);

      // Corner accent brackets
      const cornerLen = Math.min(12, fw * 0.25);
      this.ctx.strokeStyle = '#ff2e63';
      this.ctx.lineWidth = 3;

      // Top-Left
      this.ctx.beginPath();
      this.ctx.moveTo(fx, fy + cornerLen);
      this.ctx.lineTo(fx, fy);
      this.ctx.lineTo(fx + cornerLen, fy);
      this.ctx.stroke();

      // Top-Right
      this.ctx.beginPath();
      this.ctx.moveTo(fx + fw - cornerLen, fy);
      this.ctx.lineTo(fx + fw, fy);
      this.ctx.lineTo(fx + fw, fy + cornerLen);
      this.ctx.stroke();

      // Bottom-Left
      this.ctx.beginPath();
      this.ctx.moveTo(fx, fy + fh - cornerLen);
      this.ctx.lineTo(fx, fy + fh);
      this.ctx.lineTo(fx + cornerLen, fy + fh);
      this.ctx.stroke();

      // Bottom-Right
      this.ctx.beginPath();
      this.ctx.moveTo(fx + fw - cornerLen, fy + fh);
      this.ctx.lineTo(fx + fw, fy + fh);
      this.ctx.lineTo(fx + fw, fy + fh - cornerLen);
      this.ctx.stroke();

      // Confidence label tag
      this.ctx.fillStyle = 'rgba(11, 12, 16, 0.85)';
      this.ctx.fillRect(fx, Math.max(0, fy - 20), 85, 18);
      this.ctx.font = "bold 10px 'JetBrains Mono', monospace";
      this.ctx.fillStyle = '#00fff5';
      this.ctx.fillText(`FACE ${Math.round(closestFace.confidence * 100)}%`, fx + 4, Math.max(12, fy - 7));

      this.ctx.restore();
    }

    // 2. Draw 17-Point Pose Skeleton
    if (showPose && closestPose && closestPose.landmarks) {
      const lms = closestPose.landmarks;
      const POSE_BONES = [
        [0, 1], [0, 2], [1, 3], [2, 4], // Head
        [5, 6],                          // Shoulders
        [5, 7], [7, 9],                  // Left arm
        [6, 8], [8, 10],                 // Right arm
        [5, 11], [6, 12],                // Torso
        [11, 12],                        // Hips
        [11, 13], [13, 15],              // Left leg
        [12, 14], [14, 16],              // Right leg
      ];

      this.ctx.save();
      this.ctx.strokeStyle = 'rgba(255, 46, 99, 0.75)';
      this.ctx.lineWidth = 2.5;

      // Draw bone connections
      POSE_BONES.forEach(([idx1, idx2]) => {
        const p1 = lms.find(l => l.landmark_index === idx1);
        const p2 = lms.find(l => l.landmark_index === idx2);
        if (p1 && p2 && p1.visibility > 0.4 && p2.visibility > 0.4) {
          this.ctx.beginPath();
          this.ctx.moveTo(p1.x * w, p1.y * h);
          this.ctx.lineTo(p2.x * w, p2.y * h);
          this.ctx.stroke();
        }
      });

      // Draw keypoint joints
      lms.forEach(lm => {
        if (lm.visibility > 0.4) {
          const kx = lm.x * w;
          const ky = lm.y * h;

          this.ctx.beginPath();
          this.ctx.arc(kx, ky, 3.5, 0, Math.PI * 2);
          this.ctx.fillStyle = '#00fff5';
          this.ctx.fill();
          this.ctx.strokeStyle = '#0b0c10';
          this.ctx.lineWidth = 1;
          this.ctx.stroke();
        }
      });

      this.ctx.restore();
    }
  }
}
