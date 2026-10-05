/**
 * ===================================================================
 * 3D REEL STUDIO — Main Application Orchestrator
 * Phase 1 Frontend Foundation
 * ===================================================================
 * 
 * Central controller managing media ingestion, live player sync,
 * face reference pairing, canvas overlay lifecycle, and backend placeholders.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Initialize Core Subsystems
  const canvasElement = document.getElementById('canvas-overlay');
  const videoElement = document.getElementById('video-player');
  const pipelineTrack = document.getElementById('pipeline-track');
  const terminalBody = document.getElementById('terminal-body');
  const terminalToggleBtn = document.getElementById('btn-toggle-terminal');

  // Instantiate Sub-Controllers
  window.canvasEngine = new KineticCanvasEngine(canvasElement, videoElement);
  window.pipelineController = new PipelineController(pipelineTrack, terminalBody, terminalToggleBtn);
  window.uiController = new UIController();

  // Initialize App Features
  initVideoIngestion();
  initFaceReference();
  initPlayerControls();
  initReelUrlInput();
  initGenerateAction();
  initSafeZoneGuides();
  initDemoKineticToggle();
  initBackendConnection();
  initTranscriptionControls();
  initSceneAnalysisControls();
  initVisionControls();
  initComicGenerationControls();
  initConsistencyControls();
  initSegmentationControls();
  initLyricsControls();
  initRenderControls();
  initAuthControls();
});

/**
 * Initialize FastAPI backend connectivity and status probing
 */
function initBackendConnection() {
  if (typeof checkBackendHealth === 'function') {
    // Initial health check on page load
    checkBackendHealth(false);

    // Periodic non-intrusive status polling
    setInterval(() => {
      checkBackendHealth(true);
    }, 15000);
  }

  // Click handler on status pill to manually refresh backend status
  const statusIndicator = document.getElementById('system-status-indicator');
  if (statusIndicator) {
    statusIndicator.style.cursor = 'pointer';
    statusIndicator.addEventListener('click', async () => {
      showToast('Probing FastAPI backend status...', 'info');
      const isOnline = await checkBackendHealth(false);
      if (isOnline) {
        showToast('FastAPI Backend is Online and Healthy!', 'success');
      } else {
        showToast('FastAPI Backend is Offline (Start with uvicorn app.main:app)', 'warning');
      }
    });
  }
}

/* ===================================================================
   PHASE 4: FASTAPI MEDIA UPLOAD & PERSISTENCE ORCHESTRATION
   =================================================================== */

/**
 * Ensures an active, valid project exists in SQLite database before media uploads.
 * @returns {Promise<string>} Active project ID
 */
async function ensureActiveProject() {
  if (appState.projectId) {
    try {
      if (typeof getProjectAPI === 'function') {
        const existing = await getProjectAPI(appState.projectId);
        if (existing && existing.id) return existing.id;
      }
    } catch (e) {
      // Not in DB or newly initialized
    }
  }

  // Create active project in SQLite
  try {
    if (typeof createProjectAPI === 'function') {
      const created = await createProjectAPI(appState.projectName || "Default 3D Reel");
      if (created && created.id) {
        appState.projectId = created.id;
        appState.projectName = created.name;
        return created.id;
      }
    }
  } catch (e) {
    // Backend offline; fallback to current in-memory ID
  }
  return appState.projectId;
}

/**
 * Ingest and select video file in studio
 * @param {File} file 
 */
function selectVideo(file) {
  if (!file) return;

  // Local format and size validation (max 500MB)
  const validExts = ['.mp4', '.mov', '.webm'];
  const ext = (file.name.substring(file.name.lastIndexOf('.')) || '').toLowerCase();
  const validTypes = ['video/mp4', 'video/quicktime', 'video/webm'];

  if (!validExts.includes(ext) && !validTypes.includes(file.type)) {
    showToast('Invalid video format. Please upload MP4, MOV, or WEBM.', 'error');
    window.pipelineController.updateStatus(`Rejected file: ${file.name} (Unsupported format: ${ext || file.type})`, 'error');
    return;
  }

  if (file.size === 0) {
    showToast('Uploaded video is empty (0 bytes).', 'error');
    return;
  }

  const maxVideoBytes = 500 * 1024 * 1024;
  if (file.size > maxVideoBytes) {
    showToast('Video exceeds maximum allowed size of 500 MB.', 'error');
    return;
  }

  // Update App State
  appState.videoFile = file;
  appState.videoMediaId = null;
  if (appState.videoUrl) {
    URL.revokeObjectURL(appState.videoUrl);
  }
  appState.videoUrl = URL.createObjectURL(file);

  appState.videoMetadata.name = file.name;
  appState.videoMetadata.size = file.size;
  appState.videoMetadata.formattedSize = formatBytes(file.size);
  appState.videoMetadata.type = file.type || 'video/mp4';

  // Mount to Video Player (local preview stays completely responsive)
  const video = document.getElementById('video-player');
  const emptyState = document.getElementById('empty-preview-state');
  const reelFrame = document.querySelector('.reel-frame');

  video.src = appState.videoUrl;
  video.load();

  video.onloadedmetadata = () => {
    appState.videoMetadata.duration = video.duration;
    appState.videoMetadata.formattedDuration = formatTime(video.duration);
    appState.videoMetadata.width = video.videoWidth;
    appState.videoMetadata.height = video.videoHeight;

    // Update UI Metadata Cards & Badges
    renderVideoMetaCard();
    updateLiveStageSpecs();

    // Enable Video Viewport
    video.classList.add('active');
    if (emptyState) emptyState.classList.add('hidden');
    if (reelFrame) reelFrame.classList.add('has-video');

    // Resize canvas to match the freshly rendered video
    window.canvasEngine.resizeCanvas();

    // Enable Generate Button
    const btnGen = document.getElementById('btn-generate-reel');
    if (btnGen) btnGen.removeAttribute('disabled');

    // Update Stage 1 in Pipeline
    window.pipelineController.updatePipelineStage(1, 'completed', `Loaded "${file.name}" (${appState.videoMetadata.formattedSize}, ${appState.videoMetadata.formattedDuration}, ${appState.videoMetadata.width}x${appState.videoMetadata.height})`);
    showToast(`Video "${file.name}" loaded successfully`, 'success');

    // Asynchronously upload video to backend storage
    uploadVideo(file);
  };

  video.onerror = () => {
    showToast('Error loading video preview', 'error');
    window.pipelineController.updateStatus(`Failed to parse video preview for ${file.name}`, 'error');
  };
}

/**
 * Upload video binary to FastAPI backend server
 * POST /api/v1/projects/{project_id}/media
 * @param {File} videoFile 
 */
async function uploadVideo(videoFile) {
  if (!videoFile) return;

  appState.isUploadingVideo = true;
  window.pipelineController.updatePipelineStage(1, 'processing', `Uploading "${videoFile.name}" to server storage...`);

  try {
    const projectId = await ensureActiveProject();
    window.pipelineController.updateStatus(`[Upload Initiated] Streaming "${videoFile.name}" (${formatBytes(videoFile.size)}) to project ${projectId}...`, 'info');

    const res = await uploadMediaAPI(projectId, videoFile, 'source_video', (percent) => {
      window.pipelineController.updatePipelineStage(1, 'processing', `Uploading "${videoFile.name}" (${percent}%)...`);
    });

    if (res && res.success && res.media) {
      appState.videoMediaId = res.media.id;
      appState.isUploadingVideo = false;

      window.pipelineController.updatePipelineStage(
        1,
        'completed',
        `Secured "${videoFile.name}" in project storage (Media ID: ${res.media.id.substring(0, 8)}...)`
      );

      const hashDisplay = res.media.sha256_hash ? ` | SHA-256: ${res.media.sha256_hash.substring(0, 10)}...` : '';
      window.pipelineController.updateStatus(
        `[Upload Complete] Source video stored securely in backend storage.${hashDisplay} Media ID: ${res.media.id}`,
        'success'
      );
      showToast('Video uploaded and saved to server storage!', 'success');

      // Automatically trigger Phase 5 FFmpeg audio extraction once source video is stored
      triggerAudioExtraction(projectId, res.media.id);

      // Automatically trigger Phase 7 FFmpeg video scene & content analysis
      triggerVideoAnalysis(projectId, res.media.id);
    }
  } catch (err) {
    appState.isUploadingVideo = false;
    if (appState.backendStatus === 'offline' || (err.message && err.message.includes('Network error'))) {
      window.pipelineController.updateStatus(
        `[Local Mode] Backend offline at ${API_BASE_URL}. Video active in browser memory for local studio workflows.`,
        'info'
      );
      window.pipelineController.updatePipelineStage(1, 'completed', `Loaded locally: "${videoFile.name}" (${appState.videoMetadata.formattedSize})`);
    } else {
      window.pipelineController.updateStatus(`[Upload Failed] ${err.message}`, 'error');
      window.pipelineController.updatePipelineStage(1, 'failed', `Upload error: ${err.message}`);
      showToast(`Upload error: ${err.message}`, 'error');
    }
  }
}

/**
 * Triggers FFmpeg audio extraction pipeline stage for uploaded video
 * POST /api/v1/projects/{project_id}/media/{media_id}/extract-audio
 * @param {string} projectId 
 * @param {string} mediaId 
 */
async function triggerAudioExtraction(projectId, mediaId) {
  if (!projectId || !mediaId) return;

  appState.isExtractingAudio = true;
  window.pipelineController.updatePipelineStage(2, 'processing', 'Preparing audio extraction...');
  window.pipelineController.updateStatus(`[FFmpeg Audio Engine] Preparing audio extraction for source media ${mediaId.substring(0, 8)}...`, 'info');

  try {
    window.pipelineController.updatePipelineStage(2, 'processing', 'Extracting audio...');
    const audioMedia = await extractAudioAPI(projectId, mediaId);

    if (audioMedia && audioMedia.id) {
      appState.audioMediaId = audioMedia.id;
      appState.isExtractingAudio = false;

      window.pipelineController.updatePipelineStage(
        2,
        'completed',
        'Audio extraction complete.'
      );
      window.pipelineController.updateStatus(
        `[FFmpeg Audio Engine] Audio extraction complete. Stored MP3: "${audioMedia.stored_filename}" (${formatBytes(audioMedia.file_size)}), Media ID: ${audioMedia.id}`,
        'success'
      );
      showToast('Audio extraction complete.', 'success');

      // Automatically trigger Phase 6 OpenAI transcription once audio is extracted
      triggerTranscription(projectId, audioMedia.id);
    }
  } catch (err) {
    appState.isExtractingAudio = false;
    const safeErrorMsg = err?.message || 'Audio extraction failed.';
    window.pipelineController.updatePipelineStage(2, 'failed', `Audio extraction failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[FFmpeg Error] Audio extraction failed: ${safeErrorMsg}`, 'error');
    showToast(`Audio extraction failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Triggers OpenAI Whisper transcription pipeline stage for extracted audio
 * POST /api/v1/projects/{project_id}/media/{media_id}/transcribe
 * @param {string} projectId 
 * @param {string} mediaId 
 */
async function triggerTranscription(projectId, mediaId) {
  if (!projectId || !mediaId) return;

  appState.isTranscribing = true;
  window.pipelineController.updatePipelineStage(3, 'processing', 'Preparing transcription...');
  window.pipelineController.updateStatus(`[Whisper AI] Preparing transcription for audio media ${mediaId.substring(0, 8)}...`, 'info');

  try {
    window.pipelineController.updatePipelineStage(3, 'processing', 'Transcribing audio...');
    const transcript = await transcribeAudioAPI(projectId, mediaId);

    if (transcript && transcript.id) {
      appState.transcriptId = transcript.id;
      appState.language = transcript.language;
      appState.fullText = transcript.full_text;
      appState.segments = transcript.segments || [];
      appState.isTranscribing = false;

      window.pipelineController.updatePipelineStage(
        3,
        'completed',
        'Transcription complete.'
      );
      window.pipelineController.updateStatus(
        `[Whisper AI] Transcription complete. Language: "${transcript.language || 'auto'}", Segments: ${transcript.segments ? transcript.segments.length : 0}, ID: ${transcript.id}`,
        'success'
      );
      showToast('Transcription complete.', 'success');

      // Update Transcript UI Panel
      renderTranscriptPanel(transcript);
    }
  } catch (err) {
    appState.isTranscribing = false;
    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Transcription failed.';
    window.pipelineController.updatePipelineStage(3, 'failed', `Transcription failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Whisper AI Error] Transcription failed: ${safeErrorMsg}`, 'error');
    showToast(`Transcription failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Format timestamp in seconds into mm:ss.SS (e.g. 00:00.52)
 * @param {number} sec 
 * @returns {string}
 */
function formatTimestampSeconds(sec) {
  if (isNaN(sec) || sec < 0) return '00:00.00';
  const mins = Math.floor(sec / 60);
  const remainder = sec % 60;
  const secsFormatted = remainder.toFixed(2).padStart(5, '0');
  return `${mins.toString().padStart(2, '0')}:${secsFormatted}`;
}

/**
 * Helper to escape HTML characters
 * @param {string} str 
 * @returns {string}
 */
function escapeHtmlString(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Renders transcript language, full text, and timestamped segments in Studio Inspector
 * @param {Object} transcript 
 */
function renderTranscriptPanel(transcript) {
  if (!transcript) return;

  const langEl = document.getElementById('val-transcript-lang');
  const audioIdEl = document.getElementById('val-transcript-audio-id');
  const fullTextEl = document.getElementById('transcript-full-text');
  const countEl = document.getElementById('val-segments-count');
  const listEl = document.getElementById('transcript-segments-container');
  const btnRetranscribe = document.getElementById('btn-retranscribe');

  if (langEl) {
    langEl.textContent = (transcript.language || 'Detected').toUpperCase();
  }
  if (audioIdEl && transcript.audio_media_id) {
    audioIdEl.textContent = `${transcript.audio_media_id.substring(0, 12)}...`;
  }
  if (btnRetranscribe) {
    btnRetranscribe.style.display = 'inline-block';
  }

  if (fullTextEl) {
    fullTextEl.textContent = transcript.full_text || 'No speech detected.';
  }

  const segments = transcript.segments || [];
  if (countEl) {
    countEl.textContent = `${segments.length} Segment${segments.length === 1 ? '' : 's'}`;
  }

  if (listEl) {
    if (segments.length === 0) {
      listEl.innerHTML = '<div class="transcript-empty-placeholder">No timestamped speech segments found in audio.</div>';
      return;
    }

    listEl.innerHTML = '';
    segments.forEach((seg, idx) => {
      const card = document.createElement('div');
      card.className = 'transcript-segment-card';

      const startFormatted = formatTimestampSeconds(seg.start_time);
      const endFormatted = formatTimestampSeconds(seg.end_time);

      card.innerHTML = `
        <div class="transcript-segment-header">
          <span class="transcript-time-badge">${startFormatted} → ${endFormatted}</span>
          <span class="transcript-seq-badge">#${seg.sequence !== undefined ? seg.sequence : idx}</span>
        </div>
        <div class="transcript-segment-text">${escapeHtmlString(seg.text || '')}</div>
      `;

      listEl.appendChild(card);
    });
  }
}

/* ===================================================================
   PHASE 7: VIDEO SCENE & CONTENT ANALYSIS ORCHESTRATION
   =================================================================== */

/**
 * Triggers FFmpeg scene detection and keyframe extraction pipeline stage
 * POST /api/v1/projects/{project_id}/media/{media_id}/analyze
 * @param {string} projectId 
 * @param {string} mediaId 
 */
async function triggerVideoAnalysis(projectId, mediaId) {
  if (!projectId || !mediaId) return;

  appState.isAnalyzingVideo = true;
  window.pipelineController.updatePipelineStage(4, 'processing', 'Preparing video analysis...');
  window.pipelineController.updateStatus(`[Video Scene Engine] Preparing video scene analysis for source media ${mediaId.substring(0, 8)}...`, 'info');

  try {
    window.pipelineController.updatePipelineStage(4, 'processing', 'Analyzing scenes...');

    const analysis = await analyzeVideoAPI(projectId, mediaId);

    if (analysis && analysis.id) {
      window.pipelineController.updatePipelineStage(4, 'processing', 'Extracting keyframes...');

      appState.videoAnalysis = analysis;
      appState.isAnalyzingVideo = false;

      window.pipelineController.updatePipelineStage(
        4,
        'completed',
        'Video analysis complete.'
      );

      const sceneCount = analysis.scenes ? analysis.scenes.length : 0;
      window.pipelineController.updateStatus(
        `[Video Scene Engine] Video analysis complete. Resolution: ${analysis.width}x${analysis.height}, FPS: ${analysis.fps}, Duration: ${analysis.duration.toFixed(2)}s, Scenes: ${sceneCount}, ID: ${analysis.id}`,
        'success'
      );
      showToast('Video analysis complete.', 'success');

      // Update Scenes Inspector Panel
      renderSceneAnalysisPanel(analysis);

      // Automatically trigger Phase 8 Face Detection & Pose Tracking
      triggerVisionAnalysis(projectId, mediaId);
    }
  } catch (err) {
    appState.isAnalyzingVideo = false;
    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Video analysis failed.';
    window.pipelineController.updatePipelineStage(4, 'failed', `Video analysis failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Video Scene Engine Error] Video analysis failed: ${safeErrorMsg}`, 'error');
    showToast(`Video analysis failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Renders video stream metadata and scene breakdown in Studio Inspector
 * @param {Object} analysis 
 */
function renderSceneAnalysisPanel(analysis) {
  if (!analysis) return;

  const resEl = document.getElementById('val-meta-resolution');
  const ratioEl = document.getElementById('val-meta-ratio');
  const fpsEl = document.getElementById('val-meta-fps');
  const durEl = document.getElementById('val-meta-duration');
  const codecEl = document.getElementById('val-meta-codec');
  const countEl = document.getElementById('val-scenes-count');
  const listEl = document.getElementById('scenes-container');
  const btnReanalyze = document.getElementById('btn-reanalyze-video');

  if (resEl) {
    resEl.textContent = `${analysis.width || 0} × ${analysis.height || 0}`;
  }
  if (ratioEl) {
    ratioEl.textContent = analysis.aspect_ratio || '--';
  }
  if (fpsEl) {
    const fpsVal = analysis.fps ? `${Math.round(analysis.fps * 100) / 100} FPS` : '--';
    const framesVal = analysis.frame_count ? ` (${analysis.frame_count} frames)` : '';
    fpsEl.textContent = `${fpsVal}${framesVal}`;
  }
  if (durEl) {
    durEl.textContent = analysis.duration ? `${analysis.duration.toFixed(2)}s` : '--';
  }
  if (codecEl) {
    const codecPart = (analysis.codec || 'h264').toUpperCase();
    const pixPart = analysis.pixel_format ? ` / ${analysis.pixel_format}` : '';
    codecEl.textContent = `${codecPart}${pixPart}`;
  }
  if (btnReanalyze) {
    btnReanalyze.style.display = 'inline-block';
  }

  const scenes = analysis.scenes || [];
  if (countEl) {
    countEl.textContent = `${scenes.length} Scene${scenes.length === 1 ? '' : 's'}`;
  }

  // Populate 3D Comic Generation Scene Selector (Phase 9)
  const selectGenScene = document.getElementById('select-generation-scene');
  if (selectGenScene) {
    selectGenScene.innerHTML = '<option value="all">⚡ All Detected Scenes (Batch)</option>';
    scenes.forEach((scene, idx) => {
      const sceneNum = String((scene.sequence !== undefined ? scene.sequence : idx) + 1).padStart(2, '0');
      const startFormatted = formatTimestampSeconds(scene.start_time);
      const opt = document.createElement('option');
      opt.value = scene.id;
      opt.textContent = `Scene ${sceneNum} (@ ${startFormatted})`;
      selectGenScene.appendChild(opt);
    });
  }

  // Populate Identity & Temporal Consistency Scene Selector (Phase 10)
  const selectConsScene = document.getElementById('select-consistency-scene');
  if (selectConsScene) {
    selectConsScene.innerHTML = '<option value="all">⚡ All Comic Scenes (Sequential Batch)</option>';
    scenes.forEach((scene, idx) => {
      const sceneNum = String((scene.sequence !== undefined ? scene.sequence : idx) + 1).padStart(2, '0');
      const startFormatted = formatTimestampSeconds(scene.start_time);
      const opt = document.createElement('option');
      opt.value = scene.id;
      opt.textContent = `Scene ${sceneNum} (@ ${startFormatted})`;
      selectConsScene.appendChild(opt);
    });
  }

  if (listEl) {
    if (scenes.length === 0) {
      listEl.innerHTML = '<div class="scenes-empty-placeholder">No visual scene transitions detected in video.</div>';
      return;
    }

    listEl.innerHTML = '';
    scenes.forEach((scene, idx) => {
      const card = document.createElement('div');
      card.className = 'scene-item-card';

      const startFormatted = formatTimestampSeconds(scene.start_time);
      const endFormatted = formatTimestampSeconds(scene.end_time);
      const durationFormatted = scene.duration ? `${scene.duration.toFixed(2)}s` : '0.00s';
      const sceneNum = String((scene.sequence !== undefined ? scene.sequence : idx) + 1).padStart(2, '0');

      let keyframeHtml = '';
      if (scene.keyframe && scene.keyframe.media_file_id) {
        const kfTime = formatTimestampSeconds(scene.keyframe.timestamp);
        const kfUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(scene.keyframe.media_file_id)}/file`;
        keyframeHtml = `
          <div class="scene-keyframe-preview-box">
            <img class="scene-keyframe-img" src="${kfUrl}" alt="Scene ${sceneNum} Keyframe" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:11px;\\'>Keyframe unavailable</span>'">
            <span class="scene-keyframe-badge">Keyframe @ ${kfTime}</span>
          </div>
        `;
      } else {
        keyframeHtml = `
          <div class="scene-keyframe-preview-box">
            <span class="text-muted font-mono" style="font-size: 11px;">No Keyframe</span>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="scene-card-header">
          <span class="scene-title-badge">Scene ${sceneNum}</span>
          <span class="scene-time-badge">${startFormatted} → ${endFormatted}</span>
        </div>
        <div class="scene-meta-row">
          <span>Duration: <span class="scene-duration-tag">${durationFormatted}</span></span>
          <span class="font-mono text-muted">ID: ${scene.id ? scene.id.substring(0, 8) : '#' + idx}</span>
        </div>
        ${keyframeHtml}
      `;

      listEl.appendChild(card);
    });
  }
}

/* ===================================================================
   PHASE 8: FACE DETECTION, IDENTITY REFERENCE & POSE TRACKING
   =================================================================== */

/**
 * Triggers Face Detection, Identity Reference & Body Pose Tracking
 * POST /api/v1/projects/{project_id}/media/{media_id}/vision-analysis
 * @param {string} projectId 
 * @param {string} mediaId 
 */
async function triggerVisionAnalysis(projectId, mediaId) {
  if (!projectId || !mediaId) return;

  appState.isAnalyzingVision = true;
  window.pipelineController.updatePipelineStage(5, 'processing', 'Preparing vision analysis...');
  window.pipelineController.updateStatus(`[Vision & Pose Engine] Preparing face detection & body pose analysis for source media ${mediaId.substring(0, 8)}...`, 'info');

  try {
    window.pipelineController.updatePipelineStage(5, 'processing', 'Detecting faces...');
    window.pipelineController.updateStatus('[Vision & Pose Engine] Localizing face bounding boxes and landmark points...', 'info');

    const res = await analyzeVisionAPI(projectId, mediaId);

    if (res && res.analysis && res.analysis.id) {
      window.pipelineController.updatePipelineStage(5, 'processing', 'Selecting identity references...');
      window.pipelineController.updatePipelineStage(5, 'processing', 'Estimating body pose...');

      const analysis = res.analysis;
      appState.visionAnalysis = analysis;
      appState.isAnalyzingVision = false;

      window.pipelineController.updatePipelineStage(
        5,
        'completed',
        'Vision analysis complete.'
      );

      const faceCount = analysis.faces_detected || 0;
      const poseCount = analysis.pose_frames || 0;
      const refCount = (analysis.face_references || []).length;
      const subjectCount = (analysis.subjects || []).length;

      window.pipelineController.updateStatus(
        `[Vision & Pose Engine] Vision analysis complete. Faces: ${faceCount}, Pose Frames: ${poseCount}, Face Refs: ${refCount}, Subjects: ${subjectCount}, ID: ${analysis.id}`,
        'success'
      );
      showToast('Vision analysis complete.', 'success');

      // Update Vision Inspector Panel
      renderVisionPanel(analysis);

      // Draw initial overlays on video player
      const video = document.getElementById('video-player');
      if (video && window.canvasEngine) {
        window.canvasEngine.drawVisionOverlays(analysis, video.currentTime || 0);
      }
    }
  } catch (err) {
    appState.isAnalyzingVision = false;
    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Vision analysis failed.';
    window.pipelineController.updatePipelineStage(5, 'failed', `Vision analysis failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Vision & Pose Engine Error] Vision analysis failed: ${safeErrorMsg}`, 'error');
    showToast(`Vision analysis failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Renders face detection, primary subject tracking, and pose data in Studio Inspector
 * @param {Object} analysis 
 */
function renderVisionPanel(analysis) {
  if (!analysis) return;

  const primaryStatusEl = document.getElementById('val-vision-primary-status');
  const confEl = document.getElementById('val-vision-confidence');
  const facesCountEl = document.getElementById('val-vision-faces-count');
  const poseFramesEl = document.getElementById('val-vision-pose-frames');
  const faceRefsCountEl = document.getElementById('val-vision-face-refs-count');
  const faceRefsContainer = document.getElementById('vision-face-ref-container');
  const subjectsCountEl = document.getElementById('val-vision-subjects-count');
  const subjectsContainer = document.getElementById('vision-subjects-container');
  const btnReanalyze = document.getElementById('btn-reanalyze-vision');

  if (btnReanalyze) {
    btnReanalyze.style.display = 'inline-block';
  }

  const subjects = analysis.subjects || [];
  const primarySubject = subjects.find(s => s.is_primary) || subjects[0];

  if (primaryStatusEl) {
    if (primarySubject) {
      primaryStatusEl.textContent = `Subject #${primarySubject.sequence !== undefined ? primarySubject.sequence : 0} (Primary)`;
    } else {
      primaryStatusEl.textContent = 'None Tracked';
    }
  }

  if (confEl) {
    if (primarySubject && primarySubject.confidence !== undefined) {
      confEl.textContent = `${Math.round(primarySubject.confidence * 100)}%`;
    } else {
      confEl.textContent = '--';
    }
  }

  if (facesCountEl) {
    facesCountEl.textContent = `${analysis.faces_detected || 0} Detections`;
  }

  if (poseFramesEl) {
    poseFramesEl.textContent = `${analysis.pose_frames || 0} Frames (17 Pts)`;
  }

  const faceRefs = analysis.face_references || [];
  if (faceRefsCountEl) {
    faceRefsCountEl.textContent = `${faceRefs.length} Reference${faceRefs.length === 1 ? '' : 's'}`;
  }

  if (faceRefsContainer) {
    if (faceRefs.length === 0) {
      faceRefsContainer.innerHTML = '<div class="scenes-empty-placeholder">No high-quality face reference frames detected.</div>';
    } else {
      faceRefsContainer.innerHTML = '';
      faceRefs.forEach((ref, idx) => {
        const card = document.createElement('div');
        card.className = 'face-ref-item-card';

        const timeFormatted = formatTimestampSeconds(ref.timestamp);
        const scorePercent = Math.round((ref.quality_score || 0) * 100);
        const imgUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(ref.media_file_id)}/file`;

        card.innerHTML = `
          <div class="face-ref-thumb-box">
            <img class="face-ref-img" src="${imgUrl}" alt="Face Reference ${idx + 1}" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:11px;\\'>Ref crop unavailable</span>'">
          </div>
          <div class="face-ref-info-col">
            <div class="face-ref-header">
              <span class="face-ref-title">Identity Reference #${idx + 1}</span>
              <span class="badge badge-cyan">Quality: ${scorePercent}%</span>
            </div>
            <div class="face-ref-meta-row">
              <span>Timestamp: <strong class="font-mono text-cyan">${timeFormatted}</strong></span>
              <span class="font-mono text-muted">ID: ${ref.media_file_id ? ref.media_file_id.substring(0, 8) : '--'}</span>
            </div>
          </div>
        `;
        faceRefsContainer.appendChild(card);
      });
    }
  }

  if (subjectsCountEl) {
    subjectsCountEl.textContent = `${subjects.length} Track${subjects.length === 1 ? '' : 's'}`;
  }

  if (subjectsContainer) {
    if (subjects.length === 0) {
      subjectsContainer.innerHTML = '<div class="scenes-empty-placeholder">No tracked person subjects found.</div>';
    } else {
      subjectsContainer.innerHTML = '';
      subjects.forEach((subj, idx) => {
        const card = document.createElement('div');
        card.className = 'scene-item-card';

        const isPrimary = subj.is_primary;
        const seq = subj.sequence !== undefined ? subj.sequence : idx;
        const confPercent = Math.round((subj.confidence || 0) * 100);
        const faceCount = (subj.face_detections || []).length;
        const poseCount = (subj.pose_detections || []).length;

        card.innerHTML = `
          <div class="scene-card-header">
            <span class="scene-title-badge ${isPrimary ? '' : 'badge-optional'}">Subject #${seq}</span>
            <span class="badge ${isPrimary ? 'badge-cyan' : 'badge-optional'}">${isPrimary ? 'PRIMARY SUBJECT' : 'SECONDARY'}</span>
          </div>
          <div class="scene-meta-row" style="margin-top: 6px;">
            <span>Confidence: <strong class="font-mono text-cyan">${confPercent}%</strong></span>
            <span>Faces: <strong class="font-mono">${faceCount}</strong> | Pose: <strong class="font-mono">${poseCount}</strong></span>
          </div>
          <div class="scene-meta-row" style="margin-top: 4px;">
            <span class="font-mono text-muted" style="font-size: 11px;">Track ID: ${subj.id ? subj.id.substring(0, 12) : '--'}...</span>
          </div>
        `;
        subjectsContainer.appendChild(card);
      });
    }
  }

  // Trigger or fetch Consistency Profile preview (Phase 10)
  if (appState.projectId && typeof getConsistencyProfileAPI === 'function') {
    getConsistencyProfileAPI(appState.projectId).then(res => {
      if (res && res.profile) {
        appState.consistencyProfile = res.profile;
        renderConsistencyProfilePreview(res.profile);
      }
    }).catch(() => {
      // Profile not created yet
    });
  }
}


/**
 * Ingest and select face reference image (optional)
 * @param {File} file 
 */
function selectFaceReference(file) {
  if (!file) return;

  // Local format and size validation (max 25MB)
  const validExts = ['.jpg', '.jpeg', '.png'];
  const ext = (file.name.substring(file.name.lastIndexOf('.')) || '').toLowerCase();
  const validTypes = ['image/jpeg', 'image/png', 'image/jpg', 'image/pjpeg'];

  if (!validExts.includes(ext) && !validTypes.includes(file.type)) {
    showToast('Invalid image format. Please upload JPG, JPEG, or PNG.', 'error');
    return;
  }

  if (file.size === 0) {
    showToast('Uploaded image is empty (0 bytes).', 'error');
    return;
  }

  const maxImageBytes = 25 * 1024 * 1024;
  if (file.size > maxImageBytes) {
    showToast('Face reference exceeds maximum allowed size of 25 MB.', 'error');
    return;
  }

  appState.faceReference = file;
  appState.faceReferenceMediaId = null;
  if (appState.faceReferenceUrl) {
    URL.revokeObjectURL(appState.faceReferenceUrl);
  }
  appState.faceReferenceUrl = URL.createObjectURL(file);

  const previewBox = document.getElementById('face-preview-box');
  const descText = document.getElementById('face-desc-text');

  if (previewBox) {
    previewBox.innerHTML = `<img src="${appState.faceReferenceUrl}" alt="Face Reference Preview">`;
  }
  if (descText) {
    descText.textContent = `Attached: ${file.name} (${formatBytes(file.size)})`;
  }

  // Show remove button
  const removeBtn = document.getElementById('btn-remove-face');
  if (removeBtn) removeBtn.style.display = 'inline-flex';

  window.pipelineController.updateStatus(`Face reference image selected: ${file.name}`, 'info');
  showToast('Face reference selected', 'info');

  // Asynchronously upload face reference to backend storage
  uploadFaceReference(file);
}

/**
 * Upload face reference image to FastAPI backend server
 * POST /api/v1/projects/{project_id}/media
 * @param {File} faceFile 
 */
async function uploadFaceReference(faceFile) {
  if (!faceFile) return;

  appState.isUploadingFace = true;

  try {
    const projectId = await ensureActiveProject();
    window.pipelineController.updateStatus(`[Upload Initiated] Storing face reference "${faceFile.name}" to project ${projectId}...`, 'info');

    const res = await uploadMediaAPI(projectId, faceFile, 'face_reference');

    if (res && res.success && res.media) {
      appState.faceReferenceMediaId = res.media.id;
      appState.isUploadingFace = false;

      window.pipelineController.updateStatus(
        `[Face Reference Saved] Stored in backend storage (Media ID: ${res.media.id}).`,
        'success'
      );
      showToast('Face reference uploaded and saved.', 'info');
    }
  } catch (err) {
    appState.isUploadingFace = false;
    if (appState.backendStatus === 'offline' || (err.message && err.message.includes('Network error'))) {
      window.pipelineController.updateStatus(`[Local Mode] Face reference attached in local browser preview.`, 'info');
    } else {
      window.pipelineController.updateStatus(`[Face Reference Upload Error] ${err.message}`, 'error');
      showToast(`Face reference upload failed: ${err.message}`, 'error');
    }
  }
}

/**
 * Trigger 3D Reel Transformation pipeline
 * TODO: In Phase 2-15, trigger FastAPI POST /api/v1/generate/start
 */
function startGeneration() {
  if (!appState.videoFile) {
    showToast('Please select or drop a video first', 'warning');
    return;
  }

  // Open the Phase 1 Integration Confirmation Modal
  window.uiController.openModal('modal-generation-info');
  
  window.pipelineController.updateStatus(
    `[GENERATE REQUEST] Project: ${appState.projectId} | Style: ${appState.selectedStyle} | Lyrics: ${appState.effects.kineticLyrics ? 'ON' : 'OFF'} | FaceRef: ${appState.faceReference ? 'Attached' : 'None'}`,
    'info'
  );
}

/**
 * Proxy helper for updating pipeline stages
 */
function updatePipelineStage(stageNumber, status, detail) {
  window.pipelineController.updatePipelineStage(stageNumber, status, detail);
}

/**
 * Proxy helper for logging messages to the telemetry log
 */
function updateStatus(message, type = 'info') {
  window.pipelineController.updateStatus(message, type);
}

/* ===================================================================
   EVENT BINDINGS & UI CONTROLLERS
   =================================================================== */

/**
 * Initialize Video Upload Drag & Drop and File Picker
 */
function initVideoIngestion() {
  const dropzone = document.getElementById('video-dropzone');
  const fileInput = document.getElementById('video-file-input');
  const btnChoose = document.getElementById('btn-choose-video');

  if (btnChoose && fileInput) {
    btnChoose.addEventListener('click', () => fileInput.click());
  }

  if (dropzone && fileInput) {
    dropzone.addEventListener('click', (e) => {
      // Prevent opening if clicking nested button
      if (e.target !== btnChoose) {
        fileInput.click();
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        selectVideo(e.target.files[0]);
      }
    });

    // Drag & drop visual events
    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add('drag-active');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove('drag-active');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files[0]) {
        selectVideo(dt.files[0]);
      }
    });
  }
}

/**
 * Render Video Metadata Card in Left Panel
 */
function renderVideoMetaCard() {
  const dropzone = document.getElementById('video-dropzone');
  const metaContainer = document.getElementById('video-meta-container');

  if (dropzone) dropzone.style.display = 'none';
  if (!metaContainer) return;

  metaContainer.innerHTML = `
    <div class="file-meta-card">
      <div class="file-meta-header">
        <div class="file-icon-badge">🎬</div>
        <div class="file-meta-info">
          <div class="file-meta-name" title="${appState.videoMetadata.name}">${appState.videoMetadata.name}</div>
          <div class="file-meta-sub">
            <span>${appState.videoMetadata.formattedSize}</span>
            <span>•</span>
            <span>${appState.videoMetadata.formattedDuration}</span>
            <span>•</span>
            <span>${appState.videoMetadata.width}×${appState.videoMetadata.height}</span>
          </div>
        </div>
      </div>
      <div class="file-meta-actions">
        <button class="btn-meta-action" id="btn-replace-video">Replace Video</button>
        <button class="btn-meta-action btn-remove" id="btn-remove-video">Remove</button>
      </div>
    </div>
  `;

  metaContainer.style.display = 'block';

  // Bind Replace & Remove Actions
  const btnReplace = document.getElementById('btn-replace-video');
  const btnRemove = document.getElementById('btn-remove-video');
  const fileInput = document.getElementById('video-file-input');

  if (btnReplace && fileInput) {
    btnReplace.addEventListener('click', () => fileInput.click());
  }

  if (btnRemove) {
    btnRemove.addEventListener('click', () => {
      removeVideo();
    });
  }
}

/**
 * Reset source video from studio
 */
function removeVideo() {
  const video = document.getElementById('video-player');
  const emptyState = document.getElementById('empty-preview-state');
  const reelFrame = document.querySelector('.reel-frame');
  const dropzone = document.getElementById('video-dropzone');
  const metaContainer = document.getElementById('video-meta-container');
  const btnGen = document.getElementById('btn-generate-reel');
  const fileInput = document.getElementById('video-file-input');

  if (appState.videoUrl) {
    URL.revokeObjectURL(appState.videoUrl);
  }
  appState.videoFile = null;
  appState.videoUrl = null;
  appState.videoMediaId = null;
  appState.audioMediaId = null;
  appState.isUploadingVideo = false;
  appState.isExtractingAudio = false;
  appState.videoMetadata = { name: '', size: 0, formattedSize: '', duration: 0, formattedDuration: '', width: 0, height: 0, type: '' };
  appState.videoAnalysis = null;
  appState.isAnalyzingVideo = false;
  appState.visionAnalysis = null;
  appState.isAnalyzingVision = false;
  appState.comicGenerations = [];
  appState.currentComicGeneration = null;
  appState.isGeneratingComic = false;
  appState.consistencyProfile = null;
  appState.consistencyGenerations = [];
  appState.currentConsistencyGeneration = null;
  appState.isGeneratingConsistency = false;

  const comicFramesContainer = document.getElementById('comic-frames-container');
  if (comicFramesContainer) {
    comicFramesContainer.innerHTML = '<div class="scenes-empty-placeholder">Generated 3D comic frames and side-by-side original comparisons will appear here.</div>';
  }
  const comicStatusBox = document.getElementById('comic-gen-status-box');
  if (comicStatusBox) {
    comicStatusBox.style.display = 'none';
  }
  const comicFramesCount = document.getElementById('val-comic-frames-count');
  if (comicFramesCount) {
    comicFramesCount.textContent = '0 Frames';
  }
  const selectGenScene = document.getElementById('select-generation-scene');
  if (selectGenScene) {
    selectGenScene.innerHTML = '<option value="all">⚡ All Detected Scenes (Batch)</option>';
  }

  // Reset Phase 10 Consistency UI elements
  const canonicalContainer = document.getElementById('canonical-ref-preview-container');
  if (canonicalContainer) {
    canonicalContainer.innerHTML = '<div class="scenes-empty-placeholder">Vision &amp; pose analysis will select the canonical face reference.</div>';
  }
  const anglesContainer = document.getElementById('consistency-angles-container');
  if (anglesContainer) {
    anglesContainer.innerHTML = '';
  }
  const consistentFramesContainer = document.getElementById('consistent-frames-container');
  if (consistentFramesContainer) {
    consistentFramesContainer.innerHTML = '<div class="scenes-empty-placeholder">Consistent 3D comic frames and 3-way comparisons will appear here.</div>';
  }
  const consistencyStatusBox = document.getElementById('consistency-gen-status-box');
  if (consistencyStatusBox) {
    consistencyStatusBox.style.display = 'none';
  }
  const consistentFramesCount = document.getElementById('val-consistent-frames-count');
  if (consistentFramesCount) {
    consistentFramesCount.textContent = '0 Frames';
  }
  const selectConsScene = document.getElementById('select-consistency-scene');
  if (selectConsScene) {
    selectConsScene.innerHTML = '<option value="all">⚡ All Comic Scenes (Sequential Batch)</option>';
  }
  const consistencyStatusTag = document.getElementById('val-consistency-status-tag');
  if (consistencyStatusTag) {
    consistencyStatusTag.textContent = 'Standby';
  }

  if (video) {
    video.pause();
    video.src = '';
    video.classList.remove('active');
  }
  if (emptyState) emptyState.classList.remove('hidden');
  if (reelFrame) reelFrame.classList.remove('has-video');
  if (dropzone) dropzone.style.display = 'block';
  if (metaContainer) metaContainer.style.display = 'none';
  if (btnGen) btnGen.setAttribute('disabled', 'true');
  if (fileInput) fileInput.value = '';

  window.canvasEngine.clearCanvas();
  updateLiveStageSpecs();
  window.pipelineController.updatePipelineStage(1, 'ready', 'Source video removed.');
  window.pipelineController.updatePipelineStage(2, 'pending', 'Demux audio track');
  window.pipelineController.updatePipelineStage(3, 'pending', 'Whisper speech-to-text');
  window.pipelineController.updatePipelineStage(4, 'pending', 'Keyframe and depth map');
  window.pipelineController.updatePipelineStage(5, 'pending', 'Landmark detection');
  window.pipelineController.updatePipelineStage(6, 'pending', 'Comic stylization model');
  window.pipelineController.updatePipelineStage(7, 'pending', 'Face reference blending');
  showToast('Video removed from studio', 'info');
}

/**
 * Initialize Face Reference Upload
 */
function initFaceReference() {
  const faceBox = document.getElementById('face-preview-box');
  const faceInput = document.getElementById('face-file-input');
  const btnRemoveFace = document.getElementById('btn-remove-face');

  if (faceBox && faceInput) {
    faceBox.addEventListener('click', () => faceInput.click());
    faceInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        selectFaceReference(e.target.files[0]);
      }
    });
  }

  if (btnRemoveFace) {
    btnRemoveFace.addEventListener('click', (e) => {
      e.stopPropagation();
      if (appState.faceReferenceUrl) {
        URL.revokeObjectURL(appState.faceReferenceUrl);
      }
      appState.faceReference = null;
      appState.faceReferenceUrl = null;
      appState.faceReferenceMediaId = null;
      appState.isUploadingFace = false;
      if (faceInput) faceInput.value = '';

      if (faceBox) {
        faceBox.innerHTML = '<span class="face-preview-placeholder">👤</span>';
      }
      const descText = document.getElementById('face-desc-text');
      if (descText) {
        descText.textContent = 'Used to improve character identity consistency.';
      }
      btnRemoveFace.style.display = 'none';
      showToast('Face reference removed', 'info');
    });
  }
}

/**
 * Initialize Reel URL Input
 */
function initReelUrlInput() {
  const urlInput = document.getElementById('input-reel-url');
  if (urlInput) {
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        showToast('URL import will be available in a future version.', 'info');
        window.pipelineController.updateStatus(`[URL Input] "${urlInput.value}" — URL import engine planned for future phase.`, 'info');
      }
    });
  }
}

/**
 * Initialize Live 9:16 Video Player Controls
 */
function initPlayerControls() {
  const video = document.getElementById('video-player');
  const playBtn = document.getElementById('btn-play-pause');
  const scrubber = document.getElementById('video-scrubber');
  const timeDisplay = document.getElementById('time-display');
  const muteBtn = document.getElementById('btn-mute');
  const fullscreenBtn = document.getElementById('btn-fullscreen');

  if (!video) return;

  if (playBtn) {
    playBtn.addEventListener('click', () => {
      if (!appState.videoFile) {
        showToast('Upload a video first to play', 'info');
        return;
      }
      if (video.paused || video.ended) {
        video.play();
        playBtn.innerHTML = '⏸';
        playBtn.title = 'Pause (Space)';
      } else {
        video.pause();
        playBtn.innerHTML = '▶';
        playBtn.title = 'Play (Space)';
      }
    });
  }

  video.addEventListener('timeupdate', () => {
    if (video.duration && scrubber) {
      scrubber.value = (video.currentTime / video.duration) * 100;
      if (timeDisplay) {
        timeDisplay.textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`;
      }
    }
    // Update live vision bounding box and pose skeleton overlays
    if (window.canvasEngine && appState.visionAnalysis && !window.canvasEngine.isDemoMode) {
      window.canvasEngine.drawVisionOverlays(appState.visionAnalysis, video.currentTime);
    }
  });

  video.addEventListener('ended', () => {
    if (playBtn) {
      playBtn.innerHTML = '▶';
    }
  });

  if (scrubber) {
    scrubber.addEventListener('input', () => {
      if (video.duration) {
        video.currentTime = (scrubber.value / 100) * video.duration;
        if (window.canvasEngine && appState.visionAnalysis && !window.canvasEngine.isDemoMode) {
          window.canvasEngine.drawVisionOverlays(appState.visionAnalysis, video.currentTime);
        }
      }
    });
  }

  if (muteBtn) {
    muteBtn.addEventListener('click', () => {
      video.muted = !video.muted;
      muteBtn.innerHTML = video.muted ? '🔇' : '🔊';
      muteBtn.title = video.muted ? 'Unmute (M)' : 'Mute (M)';
    });
  }

  if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', () => {
      const container = document.querySelector('.reel-frame');
      if (!container) return;
      if (!document.fullscreenElement) {
        container.requestFullscreen().catch(err => {
          showToast(`Error attempting fullscreen: ${err.message}`, 'error');
        });
      } else {
        document.exitFullscreen();
      }
    });
  }
}

/**
 * Initialize 9:16 Social Safe Zone overlay toggle
 */
function initSafeZoneGuides() {
  const toggleBtn = document.getElementById('btn-toggle-safezones');
  const overlay = document.getElementById('safe-zone-overlay');

  if (toggleBtn && overlay) {
    toggleBtn.addEventListener('click', () => {
      const isVisible = overlay.classList.toggle('visible');
      toggleBtn.classList.toggle('active', isVisible);
      showToast(`Safe zone guides ${isVisible ? 'Enabled' : 'Disabled'}`, 'info');
    });
  }
}

/**
 * Initialize Kinetic Canvas Typography Demo Toggle
 */
function initDemoKineticToggle() {
  const demoBtn = document.getElementById('btn-demo-kinetic');
  if (demoBtn && window.canvasEngine) {
    demoBtn.addEventListener('click', () => {
      const isActive = window.canvasEngine.toggleDemoMode();
      demoBtn.classList.toggle('active', isActive);
      demoBtn.innerHTML = isActive ? '<span>✕ Stop Kinetic Demo</span>' : '<span>⚡ Preview Kinetic Text</span>';
      showToast(`Kinetic Canvas Typography Demo ${isActive ? 'Active' : 'Stopped'}`, 'info');
      window.pipelineController.updateStatus(
        `[Canvas Typography Engine] Demo mode ${isActive ? 'activated — previewing kinetic text rendering pipeline' : 'deactivated'}.`,
        'info'
      );
    });
  }
}

/**
 * Update Header specs on center stage
 */
function updateLiveStageSpecs() {
  const specsTag = document.getElementById('stage-specs-tag');
  if (!specsTag) return;

  if (appState.videoMetadata.name) {
    specsTag.textContent = `9:16 | ${appState.videoMetadata.width}×${appState.videoMetadata.height} | ${appState.videoMetadata.formattedDuration}`;
  } else {
    specsTag.textContent = '9:16 | 1080×1920 (FHD) | Standby';
  }
}

/**
 * Initialize Generate Main Button
 */
function initGenerateAction() {
  const btnGen = document.getElementById('btn-generate-reel');
  if (btnGen) {
    btnGen.addEventListener('click', () => {
      startGeneration();
    });
  }
}

/**
 * Initialize Phase 6 Transcription UI Controls
 */
function initTranscriptionControls() {
  const btnRetranscribe = document.getElementById('btn-retranscribe');
  if (btnRetranscribe) {
    btnRetranscribe.addEventListener('click', () => {
      if (!appState.projectId || !appState.audioMediaId) {
        showToast('No extracted audio media available to transcribe.', 'warning');
        return;
      }
      triggerTranscription(appState.projectId, appState.audioMediaId);
    });
  }
}

/**
 * Initialize Phase 7 Scene Analysis UI Controls
 */
function initSceneAnalysisControls() {
  const btnReanalyze = document.getElementById('btn-reanalyze-video');
  if (btnReanalyze) {
    btnReanalyze.addEventListener('click', () => {
      if (!appState.projectId || !appState.videoMediaId) {
        showToast('No source video available to analyze.', 'warning');
        return;
      }
      triggerVideoAnalysis(appState.projectId, appState.videoMediaId);
    });
  }
}

/**
 * Initialize Phase 8 Vision Analysis UI Controls
 */
function initVisionControls() {
  const btnReanalyze = document.getElementById('btn-reanalyze-vision');
  if (btnReanalyze) {
    btnReanalyze.addEventListener('click', () => {
      if (!appState.projectId || !appState.videoMediaId) {
        showToast('No source video available to analyze.', 'warning');
        return;
      }
      triggerVisionAnalysis(appState.projectId, appState.videoMediaId);
    });
  }

  const chkFaceBox = document.getElementById('chk-toggle-face-box');
  if (chkFaceBox) {
    chkFaceBox.addEventListener('change', (e) => {
      appState.visionOverlays.showFaceBox = e.target.checked;
      const video = document.getElementById('video-player');
      if (video && window.canvasEngine && appState.visionAnalysis) {
        window.canvasEngine.drawVisionOverlays(appState.visionAnalysis, video.currentTime);
      }
    });
  }

  const chkPoseSkel = document.getElementById('chk-toggle-pose-skel');
  if (chkPoseSkel) {
    chkPoseSkel.addEventListener('change', (e) => {
      appState.visionOverlays.showPoseSkeleton = e.target.checked;
      const video = document.getElementById('video-player');
      if (video && window.canvasEngine && appState.visionAnalysis) {
        window.canvasEngine.drawVisionOverlays(appState.visionAnalysis, video.currentTime);
      }
    });
  }
}

/* ===================================================================
   PHASE 9: 3D COMIC STYLE GENERATION ORCHESTRATION
   =================================================================== */

/**
 * Initialize 3D Comic Generation Controls and Event Handlers
 */
function initComicGenerationControls() {
  const selectPreset = document.getElementById('select-comic-style-preset');
  const styleTag = document.getElementById('val-comic-style-tag');
  const selectScene = document.getElementById('select-generation-scene');
  const targetBadge = document.getElementById('val-comic-target-badge');
  const btnTrigger = document.getElementById('btn-trigger-comic-gen');
  const inputDirective = document.getElementById('input-comic-prompt-directive');

  if (selectPreset) {
    selectPreset.addEventListener('change', (e) => {
      appState.comicStylePreset = e.target.value;
      if (styleTag) {
        const text = e.target.options[e.target.selectedIndex].text.split('—')[0].trim();
        styleTag.textContent = text;
      }
    });
  }

  if (selectScene) {
    selectScene.addEventListener('change', (e) => {
      appState.selectedGenerationSceneId = e.target.value;
      if (targetBadge) {
        targetBadge.textContent = e.target.value === 'all' ? 'Batch Ready' : 'Single Scene';
      }
    });
  }

  if (btnTrigger) {
    btnTrigger.addEventListener('click', async () => {
      if (!appState.projectId) {
        showToast('No active project found. Upload a video first.', 'warning');
        return;
      }

      if (!appState.videoAnalysis) {
        showToast('Video scene analysis must complete before generating comic frames.', 'warning');
        return;
      }

      if (!appState.visionAnalysis) {
        showToast('Face & pose vision analysis must complete before generating comic frames.', 'warning');
        return;
      }

      const sceneId = selectScene && selectScene.value !== 'all' ? selectScene.value : null;
      const stylePreset = selectPreset ? selectPreset.value : '3d-comic';
      const promptDirective = inputDirective ? inputDirective.value.trim() || null : null;

      await triggerComicGeneration(appState.projectId, {
        scene_id: sceneId,
        style_preset: stylePreset,
        prompt_directive: promptDirective
      });
    });
  }
}

/**
 * Triggers 3D Comic Generation pipeline with real-time status progression
 * POST /api/v1/projects/{project_id}/comic-generation
 * @param {string} projectId 
 * @param {Object} options 
 */
async function triggerComicGeneration(projectId, options = {}) {
  if (!projectId) return;

  const btnTrigger = document.getElementById('btn-trigger-comic-gen');
  const statusBox = document.getElementById('comic-gen-status-box');
  const statusTitle = document.getElementById('comic-status-title');
  const statusSub = document.getElementById('comic-status-sub');

  appState.isGeneratingComic = true;
  if (btnTrigger) btnTrigger.setAttribute('disabled', 'true');

  if (statusBox) {
    statusBox.style.display = 'flex';
    statusBox.classList.remove('is-failed', 'is-completed');
  }
  if (statusTitle) statusTitle.textContent = 'Preparing generation...';
  if (statusSub) statusSub.textContent = 'Validating scene keyframes, primary subject, and pose data...';

  window.pipelineController.updatePipelineStage(6, 'processing', 'Preparing generation...');
  window.pipelineController.updateStatus(
    `[3D Comic Generation] Preparing generation for project ${projectId.substring(0, 8)}... (Preset: ${options.style_preset || '3d-comic'}, Scene: ${options.scene_id || 'Batch All'})`,
    'info'
  );

  try {
    // Step 2 progression
    if (statusTitle) statusTitle.textContent = 'Generating 3D comic frame...';
    if (statusSub) statusSub.textContent = 'Stylizing scene composition & character visual features in 9:16...';
    window.pipelineController.updatePipelineStage(6, 'processing', 'Generating 3D comic frame...');

    const res = await generateComicAPI(projectId, options);

    // Step 3 progression
    if (statusTitle) statusTitle.textContent = 'Saving generated frame...';
    if (statusSub) statusSub.textContent = 'Persisting 9:16 vertical comic frame in project storage...';
    window.pipelineController.updatePipelineStage(6, 'processing', 'Saving generated frame...');

    if (res && res.success && res.generation) {
      const generation = res.generation;
      appState.currentComicGeneration = generation;
      appState.comicGenerations.push(generation);
      appState.isGeneratingComic = false;
      if (btnTrigger) btnTrigger.removeAttribute('disabled');

      if (statusBox) statusBox.classList.add('is-completed');
      if (statusTitle) statusTitle.textContent = 'Generation complete.';
      if (statusSub) statusSub.textContent = `Generated ${generation.frames.length} frame(s) using ${generation.model}`;

      window.pipelineController.updatePipelineStage(
        6,
        'completed',
        'Generation complete.'
      );

      window.pipelineController.updateStatus(
        `[3D Comic Generation Complete] Generated ${generation.frames.length} frame(s). Model: ${generation.model}, Provider: ${generation.provider}, ID: ${generation.id}`,
        'success'
      );
      showToast('Generation complete.', 'success');

      // Update Generated Comic Frames Panel
      renderComicGenerationPanel(generation);
    }
  } catch (err) {
    appState.isGeneratingComic = false;
    if (btnTrigger) btnTrigger.removeAttribute('disabled');

    const safeErrorMsg = err?.data?.error?.message || err?.message || '3D comic generation failed.';
    if (statusBox) statusBox.classList.add('is-failed');
    if (statusTitle) statusTitle.textContent = `Generation failed: ${safeErrorMsg}`;
    if (statusSub) statusSub.textContent = 'Check backend configuration or API status.';

    window.pipelineController.updatePipelineStage(6, 'failed', `Generation failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[3D Comic Generation Error] Generation failed: ${safeErrorMsg}`, 'error');
    showToast(`Generation failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Renders Side-by-Side Original vs 3D Comic Frame Comparisons in Studio Inspector
 * @param {Object} generation 
 */
function renderComicGenerationPanel(generation) {
  if (!generation) return;

  const countEl = document.getElementById('val-comic-frames-count');
  const listEl = document.getElementById('comic-frames-container');

  const frames = generation.frames || [];
  if (countEl) {
    countEl.textContent = `${frames.length} Frame${frames.length === 1 ? '' : 's'}`;
  }

  if (listEl) {
    if (frames.length === 0) {
      listEl.innerHTML = '<div class="scenes-empty-placeholder">No generated 3D comic frames found.</div>';
      return;
    }

    listEl.innerHTML = '';
    const scenes = appState.videoAnalysis?.scenes || [];

    frames.forEach((frame, idx) => {
      const card = document.createElement('div');
      card.className = 'comic-comparison-card';

      const matchingScene = scenes.find(s => s.id === frame.scene_id) || scenes[idx];
      const sceneNum = matchingScene ? String((matchingScene.sequence !== undefined ? matchingScene.sequence : idx) + 1).padStart(2, '0') : String(idx + 1).padStart(2, '0');
      const timeFormatted = formatTimestampSeconds(frame.timestamp || (matchingScene ? matchingScene.start_time : 0));
      const modelName = generation.model || 'dall-e-3';
      const resolution = `${frame.width || 1024} × ${frame.height || 1792}`;

      // Original Keyframe Image URL
      let originalKfUrl = '';
      if (matchingScene && matchingScene.keyframe && matchingScene.keyframe.media_file_id) {
        originalKfUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(matchingScene.keyframe.media_file_id)}/file`;
      }

      // Generated 3D Comic Image URL
      const comicImgUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(frame.output_media_file_id)}/file`;

      const originalImgHtml = originalKfUrl
        ? `<img class="comic-frame-img" src="${originalKfUrl}" alt="Scene ${sceneNum} Original Keyframe" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Keyframe</span>'">`
        : `<span class="text-muted font-mono" style="font-size:10px;">No Keyframe</span>`;

      card.innerHTML = `
        <div class="comic-card-header">
          <span class="comic-scene-badge">Scene ${sceneNum}</span>
          <span class="badge badge-cyan">${timeFormatted}</span>
        </div>

        <div class="comic-side-by-side-grid">
          <div class="comic-side-frame-box">
            <span class="comic-side-label">ORIGINAL</span>
            <div class="comic-image-viewport">
              ${originalImgHtml}
            </div>
          </div>

          <div class="comic-side-frame-box">
            <span class="comic-side-label label-comic">3D COMIC</span>
            <div class="comic-image-viewport comic-glow">
              <img class="comic-frame-img" src="${comicImgUrl}" alt="Scene ${sceneNum} 3D Comic Frame" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Frame Error</span>'">
            </div>
          </div>
        </div>

        <div class="comic-meta-footer">
          <span>Model: <strong class="text-cyan">${escapeHtmlString(modelName)}</strong></span>
          <span>${resolution}</span>
          <span class="badge badge-cyan" style="font-size:9px; padding:2px 6px;">${(frame.status || 'COMPLETED').toUpperCase()}</span>
        </div>
      `;

      listEl.appendChild(card);
    });
  }
}

/* ===================================================================
   PHASE 10: IDENTITY + TEMPORAL CONSISTENCY ENGINE ORCHESTRATION
   =================================================================== */

/**
 * Initialize Phase 10 Character Consistency Controls and Event Handlers
 */
function initConsistencyControls() {
  const selectPreset = document.getElementById('select-consistency-preset');
  const styleTag = document.getElementById('val-consistency-status-tag');
  const selectScene = document.getElementById('select-consistency-scene');
  const btnTrigger = document.getElementById('btn-trigger-consistency-gen');
  const inputDirective = document.getElementById('input-consistency-directive');

  if (selectPreset) {
    selectPreset.addEventListener('change', (e) => {
      appState.consistencyStylePreset = e.target.value;
      if (styleTag) {
        const text = e.target.options[e.target.selectedIndex].text.split('—')[0].trim();
        styleTag.textContent = `Preset: ${text}`;
      }
    });
  }

  if (selectScene) {
    selectScene.addEventListener('change', (e) => {
      appState.selectedConsistencySceneId = e.target.value;
    });
  }

  if (btnTrigger) {
    btnTrigger.addEventListener('click', async () => {
      if (!appState.projectId) {
        showToast('No active project found. Upload a video first.', 'warning');
        return;
      }

      if (!appState.videoAnalysis) {
        showToast('Video scene analysis must complete before running character consistency.', 'warning');
        return;
      }

      if (!appState.visionAnalysis) {
        showToast('Face & pose vision analysis must complete before running character consistency.', 'warning');
        return;
      }

      const sceneId = selectScene && selectScene.value !== 'all' ? selectScene.value : null;
      const stylePreset = selectPreset ? selectPreset.value : 'v1-3d-comic-lock';
      const promptDirective = inputDirective ? inputDirective.value.trim() || null : null;

      await triggerConsistencyGeneration(appState.projectId, {
        scene_id: sceneId,
        style_preset: stylePreset,
        prompt_directive: promptDirective
      });
    });
  }
}

/**
 * Triggers Phase 10 Reference-Guided Consistency Generation Pipeline
 * POST /api/v1/projects/{project_id}/consistency/generate
 * @param {string} projectId 
 * @param {Object} options 
 */
async function triggerConsistencyGeneration(projectId, options = {}) {
  if (!projectId) return;

  const btnTrigger = document.getElementById('btn-trigger-consistency-gen');
  const statusBox = document.getElementById('consistency-gen-status-box');
  const statusTitle = document.getElementById('consistency-status-title');
  const statusSub = document.getElementById('consistency-status-sub');

  appState.isGeneratingConsistency = true;
  if (btnTrigger) btnTrigger.setAttribute('disabled', 'true');

  if (statusBox) {
    statusBox.style.display = 'flex';
    statusBox.classList.remove('is-failed', 'is-completed');
  }
  if (statusTitle) statusTitle.textContent = 'Preparing character reference...';
  if (statusSub) statusSub.textContent = 'Selecting canonical face reference & validating pose composition...';

  window.pipelineController.updatePipelineStage(7, 'processing', 'Preparing character reference...');
  window.pipelineController.updateStatus(
    `[Character Consistency Engine] Preparing reference-guided generation for project ${projectId.substring(0, 8)}... (Lock: ${options.style_preset || 'v1-3d-comic-lock'}, Scene: ${options.scene_id || 'Sequential Batch'})`,
    'info'
  );

  try {
    // Step 2 progression
    if (statusTitle) statusTitle.textContent = 'Building consistency profile...';
    if (statusSub) statusSub.textContent = 'Extracting non-identifying stable descriptors & multi-angle references...';
    window.pipelineController.updatePipelineStage(7, 'processing', 'Building consistency profile...');

    const res = await generateConsistencyAPI(projectId, options);

    // Step 3 progression
    if (statusTitle) statusTitle.textContent = 'Validating generated frames...';
    if (statusSub) statusSub.textContent = 'Verifying visual coherence & chaining temporal sequence context...';
    window.pipelineController.updatePipelineStage(7, 'processing', 'Validating generated frames...');

    if (res && res.success && res.generation) {
      const generation = res.generation;
      const profile = res.profile;

      appState.currentConsistencyGeneration = generation;
      appState.consistencyGenerations.push(generation);
      if (profile) appState.consistencyProfile = profile;
      appState.isGeneratingConsistency = false;
      if (btnTrigger) btnTrigger.removeAttribute('disabled');

      if (statusBox) statusBox.classList.add('is-completed');
      if (statusTitle) statusTitle.textContent = 'Consistency generation complete.';
      if (statusSub) statusSub.textContent = `Generated ${generation.frames.length} temporally coherent frame(s) [${generation.model}]`;

      window.pipelineController.updatePipelineStage(
        7,
        'completed',
        'Consistency generation complete.'
      );

      window.pipelineController.updateStatus(
        `[Consistency Generation Complete] Generated ${generation.frames.length} consistent frame(s). Model: ${generation.model}, Provider: ${generation.provider}, ID: ${generation.id}`,
        'success'
      );
      showToast('Character consistency generation complete.', 'success');

      // Update Profile Preview and Consistent Frames 3-Way Grid
      if (profile) renderConsistencyProfilePreview(profile);
      renderConsistencyPanel(generation, profile);
    }
  } catch (err) {
    appState.isGeneratingConsistency = false;
    if (btnTrigger) btnTrigger.removeAttribute('disabled');

    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Consistency generation failed.';
    if (statusBox) statusBox.classList.add('is-failed');
    if (statusTitle) statusTitle.textContent = `Consistency generation failed: ${safeErrorMsg}`;
    if (statusSub) statusSub.textContent = 'Verify that Face & Pose analysis has identified a primary subject.';

    window.pipelineController.updatePipelineStage(7, 'failed', `Consistency generation failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Consistency Engine Error] Consistency generation failed: ${safeErrorMsg}`, 'error');
    showToast(`Consistency generation failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Renders the Canonical Face Reference Card & Multi-Angle Reference Chips
 * @param {Object} profile 
 */
function renderConsistencyProfilePreview(profile) {
  if (!profile) return;

  const canonicalContainer = document.getElementById('canonical-ref-preview-container');
  const anglesContainer = document.getElementById('consistency-angles-container');
  const statusTag = document.getElementById('val-consistency-status-tag');

  if (statusTag) {
    statusTag.textContent = `Active: ${profile.style_version || 'v1-3d-comic-lock'}`;
  }

  // Canonical Reference Box
  if (canonicalContainer) {
    const ref = profile.canonical_reference;
    if (ref && ref.media_file_id) {
      const imgUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(ref.media_file_id)}/file`;
      const scorePercent = Math.round((ref.quality_score || 0.95) * 100);
      const orient = (ref.orientation || 'frontal').toUpperCase();

      canonicalContainer.innerHTML = `
        <div class="consistency-canonical-card">
          <div class="canonical-thumb-box">
            <img class="canonical-ref-img" src="${imgUrl}" alt="Canonical Character Reference" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Canonical Ref</span>'">
            <span class="canonical-badge">CANONICAL ROOT</span>
          </div>
          <div class="canonical-info-col">
            <div class="canonical-header">
              <span class="canonical-title">Primary Subject Visual Reference</span>
              <span class="badge badge-cyan">${orient}</span>
            </div>
            <div class="canonical-meta-row">
              <span>Quality Score: <strong class="text-cyan">${scorePercent}%</strong></span>
              <span>Style Lock: <strong class="font-mono text-cyan">${profile.style_version || 'v1-3d-comic-lock'}</strong></span>
            </div>
            <div class="canonical-desc-text">
              Project-local visual anchor for facial structure, hair silhouette &amp; costume continuity.
            </div>
          </div>
        </div>
      `;
    } else {
      canonicalContainer.innerHTML = '<div class="scenes-empty-placeholder">Canonical character reference ready to be compiled.</div>';
    }
  }

  // Multi-Angle References Grid
  if (anglesContainer) {
    const refs = profile.references || [];
    if (refs.length > 0) {
      anglesContainer.innerHTML = '';
      refs.forEach(r => {
        const chip = document.createElement('div');
        chip.className = 'consistency-angle-chip';
        const angleName = (r.reference_type || 'frontal').replace('_', ' ').toUpperCase();
        const score = Math.round((r.quality_score || 0.9) * 100);
        
        let thumbHtml = '';
        if (r.media_file_id) {
          const imgUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(r.media_file_id)}/file`;
          thumbHtml = `<img class="angle-chip-thumb" src="${imgUrl}" alt="${angleName}" loading="lazy">`;
        } else {
          thumbHtml = `<span class="angle-chip-icon">👤</span>`;
        }

        chip.innerHTML = `
          ${thumbHtml}
          <div class="angle-chip-details">
            <span class="angle-chip-name">${angleName}</span>
            <span class="angle-chip-score">${score}% Coherence</span>
          </div>
        `;
        anglesContainer.appendChild(chip);
      });
    } else {
      anglesContainer.innerHTML = '<span class="text-muted font-mono" style="font-size:11px;">Single canonical frontal reference active.</span>';
    }
  }
}

/**
 * Renders 3-Way Comparisons (Original -> Phase 9 Comic -> Phase 10 Consistent Comic) in Studio Inspector
 * @param {Object} generation 
 * @param {Object} [profile]
 */
function renderConsistencyPanel(generation, profile = null) {
  if (!generation) return;

  const countEl = document.getElementById('val-consistent-frames-count');
  const listEl = document.getElementById('consistent-frames-container');

  const frames = generation.frames || [];
  if (countEl) {
    countEl.textContent = `${frames.length} Frame${frames.length === 1 ? '' : 's'}`;
  }

  // Update Phase 11 target frame dropdown
  updateSegmentationTargetOptions(frames);

  if (listEl) {
    if (frames.length === 0) {
      listEl.innerHTML = '<div class="scenes-empty-placeholder">No consistent comic frames found.</div>';
      return;
    }

    listEl.innerHTML = '';
    const scenes = appState.videoAnalysis?.scenes || [];
    const comicFrames = appState.currentComicGeneration?.frames || [];

    frames.forEach((frame, idx) => {
      const card = document.createElement('div');
      card.className = 'consistent-frame-card';

      const matchingScene = scenes.find(s => s.id === frame.scene_id) || scenes[idx];
      const sceneNum = matchingScene ? String((matchingScene.sequence !== undefined ? matchingScene.sequence : idx) + 1).padStart(2, '0') : String(idx + 1).padStart(2, '0');
      const timeFormatted = formatTimestampSeconds(frame.timestamp || (matchingScene ? matchingScene.start_time : 0));
      const modelName = generation.model || 'dall-e-3';
      const resolution = `${frame.width || 1024} × ${frame.height || 1792}`;

      // 1. Original Keyframe Image URL
      let originalKfUrl = '';
      if (matchingScene && matchingScene.keyframe && matchingScene.keyframe.media_file_id) {
        originalKfUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(matchingScene.keyframe.media_file_id)}/file`;
      }

      // 2. Phase 9 Comic Frame Image URL
      let phase9ComicUrl = '';
      const matchingP9Frame = comicFrames.find(f => f.scene_id === frame.scene_id) || comicFrames[idx];
      if (matchingP9Frame && matchingP9Frame.output_media_file_id) {
        phase9ComicUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(matchingP9Frame.output_media_file_id)}/file`;
      }

      // 3. Phase 10 Consistent Comic Image URL
      const consistentImgUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(frame.output_media_file_id)}/file`;

      const originalImgHtml = originalKfUrl
        ? `<img class="comic-frame-img" src="${originalKfUrl}" alt="Scene ${sceneNum} Original Keyframe" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Keyframe</span>'">`
        : `<span class="text-muted font-mono" style="font-size:10px;">No Keyframe</span>`;

      const phase9ImgHtml = phase9ComicUrl
        ? `<img class="comic-frame-img" src="${phase9ComicUrl}" alt="Scene ${sceneNum} Phase 9 Comic" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Phase 9 Comic</span>'">`
        : `<span class="text-muted font-mono" style="font-size:10px;">Phase 9 Direct</span>`;

      // Temporal Chain Badge
      const chainBadge = frame.previous_frame_id
        ? `<span class="badge badge-cyan" title="Chained to previous consistent frame">🔗 SEQ #${frame.sequence || idx}</span>`
        : `<span class="badge badge-cyan" title="Root canonical frame">👑 ROOT SEQ #0</span>`;

      // Diagnostics snippet if available
      let diagSnippet = '';
      if (frame.provider_metadata && frame.provider_metadata.diagnostics) {
        const diag = frame.provider_metadata.diagnostics;
        const colorScore = diag.color_histogram_similarity ? `${Math.round(diag.color_histogram_similarity * 100)}%` : '--';
        const faceDetected = diag.face_detected ? '✓ Verified' : 'Standard';
        diagSnippet = `<span>Face: <strong class="text-cyan">${faceDetected}</strong></span><span>Color Match: <strong class="text-cyan">${colorScore}</strong></span>`;
      }

      card.innerHTML = `
        <div class="comic-card-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="comic-scene-badge">Scene ${sceneNum}</span>
            ${chainBadge}
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="badge badge-cyan">${timeFormatted}</span>
            <button class="btn-regen-frame" data-scene-id="${frame.scene_id}" title="Regenerate this frame with consistency conditioning">⚡ Regenerate</button>
          </div>
        </div>

        <div class="consistent-3way-grid">
          <div class="comic-side-frame-box">
            <span class="comic-side-label">1. ORIGINAL</span>
            <div class="comic-image-viewport">
              ${originalImgHtml}
            </div>
          </div>

          <div class="comic-side-frame-box">
            <span class="comic-side-label label-comic">2. PHASE 9 COMIC</span>
            <div class="comic-image-viewport">
              ${phase9ImgHtml}
            </div>
          </div>

          <div class="comic-side-frame-box">
            <span class="comic-side-label label-consistent">3. CONSISTENT 3D</span>
            <div class="comic-image-viewport consistent-glow">
              <img class="comic-frame-img" src="${consistentImgUrl}" alt="Scene ${sceneNum} Consistent Comic Frame" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Frame Error</span>'">
            </div>
          </div>
        </div>

        <div class="comic-meta-footer">
          <span>Model: <strong class="text-cyan">${escapeHtmlString(modelName)}</strong></span>
          ${diagSnippet}
          <span>${resolution}</span>
          <span class="badge badge-cyan" style="font-size:9px; padding:2px 6px;">${(frame.status || 'COMPLETED').toUpperCase()}</span>
        </div>
      `;

      // Bind per-frame regeneration button
      const regenBtn = card.querySelector('.btn-regen-frame');
      if (regenBtn) {
        regenBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const targetSceneId = regenBtn.getAttribute('data-scene-id');
          showToast(`Regenerating Scene ${sceneNum} with character consistency...`, 'info');
          await triggerConsistencyGeneration(appState.projectId, {
            scene_id: targetSceneId,
            style_preset: appState.consistencyStylePreset || 'v1-3d-comic-lock'
          });
        });
      }

      listEl.appendChild(card);
    });
  }
}

/* ===================================================================
   PHASE 11: FOREGROUND SEGMENTATION & DYNAMIC BACKGROUND ORCHESTRATION
   =================================================================== */

/**
 * Initialize Phase 11 Foreground Segmentation Controls & Event Handlers
 */
function initSegmentationControls() {
  const selectFrame = document.getElementById('select-segmentation-frame');
  const selectMode = document.getElementById('select-segmentation-bg-mode');
  const selectFeather = document.getElementById('select-segmentation-feather');
  const modeTag = document.getElementById('val-seg-mode-tag');
  const featherTag = document.getElementById('val-seg-feather-tag');
  const btnTrigger = document.getElementById('btn-trigger-segmentation');

  if (selectMode) {
    selectMode.addEventListener('change', (e) => {
      appState.backgroundMode = e.target.value;
      if (modeTag) {
        const text = e.target.options[e.target.selectedIndex].text.split('—')[0].trim();
        modeTag.textContent = text;
      }
    });
  }

  if (selectFeather && featherTag) {
    selectFeather.addEventListener('change', (e) => {
      featherTag.textContent = `${e.target.value}px`;
    });
  }

  if (selectFrame) {
    selectFrame.addEventListener('change', (e) => {
      appState.selectedSegmentationFrameId = e.target.value;
    });
  }

  if (btnTrigger) {
    btnTrigger.addEventListener('click', async () => {
      if (!appState.projectId) {
        showToast('No active project found. Upload a video first.', 'warning');
        return;
      }

      const consistentFrames = appState.currentConsistencyGeneration?.frames || [];
      if (consistentFrames.length === 0) {
        showToast('Consistent comic frames must be generated before running foreground segmentation.', 'warning');
        return;
      }

      const frameId = selectFrame && selectFrame.value !== 'all' ? selectFrame.value : null;
      const bgMode = selectMode ? selectMode.value : 'ORIGINAL';
      const featherVal = selectFeather ? parseInt(selectFeather.value, 10) : 3;

      await triggerForegroundSegmentation(appState.projectId, {
        consistent_frame_id: frameId,
        background_mode: bgMode,
        refinement_params: {
          blur_radius: featherVal,
          hole_fill: true,
        },
      });
    });
  }
}

/**
 * Triggers Phase 11 Foreground Character Isolation & Background Layering
 * POST /api/v1/projects/{project_id}/segmentation
 * @param {string} projectId 
 * @param {Object} options 
 */
async function triggerForegroundSegmentation(projectId, options = {}) {
  if (!projectId) return;

  const btnTrigger = document.getElementById('btn-trigger-segmentation');
  const statusBox = document.getElementById('segmentation-status-box');
  const statusTitle = document.getElementById('segmentation-status-title');
  const statusSub = document.getElementById('segmentation-status-sub');

  appState.isSegmenting = true;
  if (btnTrigger) btnTrigger.setAttribute('disabled', 'true');

  if (statusBox) {
    statusBox.style.display = 'flex';
    statusBox.classList.remove('is-failed', 'is-completed');
  }
  if (statusTitle) statusTitle.textContent = 'Isolating primary character...';
  if (statusSub) statusSub.textContent = 'Executing subject-guided GrabCut matting & pose boundary refinement...';

  window.pipelineController.updatePipelineStage(8, 'processing', 'Reconstructing clean background layer...');
  window.pipelineController.updatePipelineStage(9, 'processing', 'Generating refined soft alpha mask...');
  window.pipelineController.updateStatus(
    `[Foreground Matting & Background Layering] Starting segmentation for project ${projectId.substring(0, 8)}... (Mode: ${options.background_mode || 'ORIGINAL'})`,
    'info'
  );

  try {
    const res = await segmentForegroundAPI(projectId, options);

    if (res && res.success && res.results) {
      const results = res.results;
      appState.segmentationResults = results;
      appState.currentSegmentationResult = results[0] || null;
      appState.isSegmenting = false;
      if (btnTrigger) btnTrigger.removeAttribute('disabled');

      if (statusBox) statusBox.classList.add('is-completed');
      if (statusTitle) statusTitle.textContent = 'Segmentation & layering complete.';
      if (statusSub) statusSub.textContent = `Generated ${results.length} multi-layer scene(s) [Mode: ${options.background_mode || 'ORIGINAL'}]`;

      window.pipelineController.updatePipelineStage(8, 'completed', 'Clean background layer generated.');
      window.pipelineController.updatePipelineStage(9, 'completed', 'Character foreground mask generated.');
      window.pipelineController.updateStatus(
        `[Layered Scene Complete] Generated ${results.length} layered scene(s) with independent FG/BG layers and composite. Mode: ${options.background_mode || 'ORIGINAL'}`,
        'success'
      );
      showToast('Foreground segmentation & background layering complete.', 'success');

      renderSegmentationPanel(results);
    }
  } catch (err) {
    appState.isSegmenting = false;
    if (btnTrigger) btnTrigger.removeAttribute('disabled');

    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Segmentation failed.';
    if (statusBox) statusBox.classList.add('is-failed');
    if (statusTitle) statusTitle.textContent = `Segmentation failed: ${safeErrorMsg}`;
    if (statusSub) statusSub.textContent = 'Ensure Phase 10 consistent frames have been generated.';

    window.pipelineController.updatePipelineStage(9, 'failed', `Segmentation failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Segmentation Error] ${safeErrorMsg}`, 'error');
    showToast(`Segmentation failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Updates the Segmentation Target selection dropdown with available consistent frames
 * @param {Array} consistentFrames 
 */
function updateSegmentationTargetOptions(consistentFrames = []) {
  const selectFrame = document.getElementById('select-segmentation-frame');
  if (!selectFrame) return;

  const currentVal = selectFrame.value;
  selectFrame.innerHTML = '<option value="all">⚡ All Consistent Frames (Batch)</option>';

  consistentFrames.forEach((frame, idx) => {
    const opt = document.createElement('option');
    opt.value = frame.id;
    const timeFormatted = formatTimestampSeconds(frame.timestamp || 0);
    opt.textContent = `Scene ${String((frame.sequence || idx) + 1).padStart(2, '0')} (${timeFormatted})`;
    selectFrame.appendChild(opt);
  });

  if (currentVal && Array.from(selectFrame.options).some(o => o.value === currentVal)) {
    selectFrame.value = currentVal;
  }
}

/**
 * Renders the Multi-Layer breakdown (Alpha Mask -> Foreground RGBA -> Background -> Composite)
 * @param {Array} results 
 */
function renderSegmentationPanel(results = []) {
  const countEl = document.getElementById('val-segmentation-count');
  const listEl = document.getElementById('segmentation-layers-container');

  if (countEl) {
    countEl.textContent = `${results.length} Scene${results.length === 1 ? '' : 's'}`;
  }

  if (listEl) {
    if (!results || results.length === 0) {
      listEl.innerHTML = '<div class="scenes-empty-placeholder">No layered scenes found. Run segmentation above.</div>';
      return;
    }

    listEl.innerHTML = '';
    const consistentFrames = appState.currentConsistencyGeneration?.frames || [];

    results.forEach((res, idx) => {
      const card = document.createElement('div');
      card.className = 'segmentation-card';

      const matchingFrame = consistentFrames.find(f => f.id === res.consistent_frame_id) || consistentFrames[idx];
      const sceneNum = matchingFrame ? String((matchingFrame.sequence !== undefined ? matchingFrame.sequence : idx) + 1).padStart(2, '0') : String(idx + 1).padStart(2, '0');
      const mode = res.background_mode || 'ORIGINAL';
      const qScore = res.quality_metrics ? Math.round((res.quality_metrics.quality_score || 0.85) * 100) : 85;
      const covScore = res.quality_metrics ? Math.round((res.quality_metrics.coverage_ratio || 0.35) * 100) : 35;

      // Media URLs
      const maskImgUrl = res.mask_media_file_id
        ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(res.mask_media_file_id)}/file`
        : '';
      const fgImgUrl = res.foreground_media_file_id
        ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(res.foreground_media_file_id)}/file`
        : '';
      const bgImgUrl = res.background_media_file_id
        ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(res.background_media_file_id)}/file`
        : '';
      const compImgUrl = res.composite_media_file_id
        ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(res.composite_media_file_id)}/file`
        : '';

      card.innerHTML = `
        <div class="segmentation-card-header">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="comic-scene-badge">Scene ${sceneNum}</span>
            <span class="badge badge-cyan">${mode}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="badge badge-cyan" title="Calculated Matting Quality Score">★ ${qScore}% Score</span>
            <button class="btn-regen-frame btn-regen-seg" data-frame-id="${res.consistent_frame_id || ''}" title="Re-segment this frame">⚡ Reprocess</button>
          </div>
        </div>

        <div class="layers-preview-grid">
          <!-- 1. Mask -->
          <div class="layer-tile">
            <div class="layer-tile-label">
              <span>1. Alpha Mask</span>
            </div>
            <img class="layer-tile-thumb mask-preview-img" src="${maskImgUrl}" alt="Scene ${sceneNum} Mask" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Mask</span>'">
          </div>

          <!-- 2. Foreground RGBA -->
          <div class="layer-tile">
            <div class="layer-tile-label">
              <span>2. Foreground</span>
            </div>
            <div class="checkerboard-bg" style="border-radius: 4px; overflow: hidden;">
              <img class="layer-tile-thumb" src="${fgImgUrl}" alt="Scene ${sceneNum} Foreground" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Foreground</span>'">
            </div>
          </div>

          <!-- 3. Background -->
          <div class="layer-tile">
            <div class="layer-tile-label">
              <span>3. Background</span>
            </div>
            <img class="layer-tile-thumb" src="${bgImgUrl}" alt="Scene ${sceneNum} Background" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Background</span>'">
          </div>

          <!-- 4. Composite -->
          <div class="layer-tile">
            <div class="layer-tile-label">
              <span>4. Composite</span>
            </div>
            <img class="layer-tile-thumb" src="${compImgUrl}" alt="Scene ${sceneNum} Composite" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Composite</span>'">
          </div>
        </div>

        <div class="layer-metrics-bar">
          <span class="metric-chip">Coverage: <strong class="text-cyan">${covScore}%</strong></span>
          <span class="metric-chip">Model: <strong class="text-cyan">${escapeHtmlString(res.model || 'grabcut_pose_prior')}</strong></span>
          <span class="metric-chip">Status: <strong class="text-cyan">${(res.status || 'COMPLETED').toUpperCase()}</strong></span>
        </div>
      `;

      // Bind per-frame reprocess button
      const reprocessBtn = card.querySelector('.btn-regen-seg');
      if (reprocessBtn) {
        reprocessBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const targetFrameId = reprocessBtn.getAttribute('data-frame-id');
          showToast(`Reprocessing Scene ${sceneNum} layers (Mode: ${appState.backgroundMode || 'ORIGINAL'})...`, 'info');
          await triggerForegroundSegmentation(appState.projectId, {
            consistent_frame_id: targetFrameId,
            background_mode: appState.backgroundMode || 'ORIGINAL',
            force_regenerate: true,
          });
        });
      }

      listEl.appendChild(card);
    });
  }
}

/* ===================================================================
   PHASE 12: KINETIC LYRICS & TEXT-BEHIND-CHARACTER ENGINE
   =================================================================== */

/**
 * Initializes Kinetic Lyrics Inspector controls, event bindings, and slider interactions
 */
function initLyricsControls() {
  const btnSync = document.getElementById('btn-sync-lyrics');
  const btnRefresh = document.getElementById('btn-refresh-lyrics');
  const btnTriggerPreview = document.getElementById('btn-trigger-lyric-preview');

  const inputText = document.getElementById('input-lyric-segment-text');
  const selectStyle = document.getElementById('select-lyric-style');
  const selectAnim = document.getElementById('select-lyric-animation');
  const sliderPosY = document.getElementById('slider-lyric-pos-y');
  const sliderPosX = document.getElementById('slider-lyric-pos-x');
  const sliderScale = document.getElementById('slider-lyric-scale');
  const sliderOpacity = document.getElementById('slider-lyric-opacity');

  const tagStyle = document.getElementById('val-lyric-style-name');
  const tagAnim = document.getElementById('val-lyric-anim-name');
  const tagPosY = document.getElementById('val-lyric-pos-y');
  const tagPosX = document.getElementById('val-lyric-pos-x');
  const tagScale = document.getElementById('val-lyric-scale');
  const tagOpacity = document.getElementById('val-lyric-opacity');

  if (btnSync) {
    btnSync.addEventListener('click', async () => {
      if (!appState.projectId) {
        showToast('No active project found. Ingest video or transcript first.', 'warning');
        return;
      }
      await syncLyrics(appState.projectId, { force_recreate: true });
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener('click', async () => {
      if (!appState.projectId) return;
      showToast('Refreshing lyric configurations...', 'info');
      await loadLyrics(appState.projectId);
    });
  }

  // Segment Text edit
  if (inputText) {
    inputText.addEventListener('change', async (e) => {
      const activeSeg = appState.lyricSegments.find(s => s.id === appState.selectedLyricSegmentId);
      if (!activeSeg) return;
      const newText = e.target.value.trim();
      activeSeg.text = newText;
      await updateActiveLyricSegment({ text: newText });
      renderLyricTimelineStrip();
    });
  }

  // Style change
  if (selectStyle) {
    selectStyle.addEventListener('change', async (e) => {
      const styleKey = e.target.value;
      if (tagStyle) {
        const optText = e.target.options[e.target.selectedIndex].text.split(':')[1]?.trim() || styleKey;
        tagStyle.textContent = optText;
      }
      const matchedStyle = appState.lyricStyles.find(s => s.name === styleKey);
      const styleId = matchedStyle ? matchedStyle.id : null;
      await updateActiveLyricSegment({ style_id: styleId });
    });
  }

  // Animation change
  if (selectAnim) {
    selectAnim.addEventListener('change', async (e) => {
      const animType = e.target.value;
      if (tagAnim) {
        const optText = e.target.options[e.target.selectedIndex].text.split('—')[0]?.trim() || animType;
        tagAnim.textContent = optText;
      }
      const matchedAnim = appState.lyricAnimations.find(a => a.animation_type === animType);
      const animId = matchedAnim ? matchedAnim.id : null;
      await updateActiveLyricSegment({ animation_id: animId });
    });
  }

  // Vertical Anchor Slider (Y)
  if (sliderPosY) {
    sliderPosY.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      if (tagPosY) {
        tagPosY.textContent = `${Math.round(val * 100)}% (Vertical Anchor)`;
      }
    });
    sliderPosY.addEventListener('change', async (e) => {
      const val = parseFloat(e.target.value);
      await updateActiveLyricSegment({ position_y: val });
    });
  }

  // Horizontal Anchor Slider (X)
  if (sliderPosX) {
    sliderPosX.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      if (tagPosX) {
        tagPosX.textContent = `${Math.round(val * 100)}% (Center)`;
      }
    });
    sliderPosX.addEventListener('change', async (e) => {
      const val = parseFloat(e.target.value);
      await updateActiveLyricSegment({ position_x: val });
    });
  }

  // Scale Slider
  if (sliderScale) {
    sliderScale.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      if (tagScale) tagScale.textContent = `${val.toFixed(1)}x`;
    });
    sliderScale.addEventListener('change', async (e) => {
      const val = parseFloat(e.target.value);
      await updateActiveLyricSegment({ scale: val });
    });
  }

  // Opacity Slider
  if (sliderOpacity) {
    sliderOpacity.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      if (tagOpacity) tagOpacity.textContent = `${Math.round(val * 100)}%`;
    });
    sliderOpacity.addEventListener('change', async (e) => {
      const val = parseFloat(e.target.value);
      await updateActiveLyricSegment({ opacity: val });
    });
  }

  // Trigger preview composite button
  if (btnTriggerPreview) {
    btnTriggerPreview.addEventListener('click', async () => {
      if (!appState.projectId) {
        showToast('No active project found. Ingest video or transcript first.', 'warning');
        return;
      }
      const activeSeg = appState.lyricSegments.find(s => s.id === appState.selectedLyricSegmentId) || appState.lyricSegments[0];
      if (!activeSeg) {
        showToast('No lyric segments available. Sync from transcript first.', 'warning');
        return;
      }

      const timestamp = activeSeg.start_time !== undefined ? activeSeg.start_time : 0.0;
      await triggerLyricPreview(appState.projectId, {
        lyric_segment_id: activeSeg.id,
        timestamp: timestamp,
      });
    });
  }
}

/**
 * Synchronizes transcript segments into editable lyric segments via FastAPI
 * @param {string} projectId 
 * @param {Object} options 
 */
async function syncLyrics(projectId, options = {}) {
  if (!projectId) return;

  const btnSync = document.getElementById('btn-sync-lyrics');
  const syncBadge = document.getElementById('val-lyrics-sync-badge');

  appState.isSyncingLyrics = true;
  if (btnSync) btnSync.setAttribute('disabled', 'true');
  if (syncBadge) syncBadge.textContent = 'Syncing...';

  window.pipelineController.updatePipelineStage(10, 'processing', 'Synchronizing Whisper transcript with kinetic engine...');
  window.pipelineController.updateStatus(`[Kinetic Lyrics] Synchronizing lyric segments for project ${projectId.substring(0, 8)}...`, 'info');

  try {
    const res = await syncLyricsAPI(projectId, options);
    if (res && res.success) {
      appState.lyricSegments = res.segments || [];
      appState.lyricStyles = res.styles || [];
      appState.lyricAnimations = res.animations || [];

      if (appState.lyricSegments.length > 0 && !appState.selectedLyricSegmentId) {
        appState.selectedLyricSegmentId = appState.lyricSegments[0].id;
      }

      appState.isSyncingLyrics = false;
      if (btnSync) btnSync.removeAttribute('disabled');
      if (syncBadge) syncBadge.textContent = 'Whisper Synced';

      window.pipelineController.updatePipelineStage(10, 'completed', `Synced ${appState.lyricSegments.length} kinetic lyric segment(s).`);
      window.pipelineController.updateStatus(`[Kinetic Lyrics Synced] ${appState.lyricSegments.length} segments ready for text-behind-character compositing.`, 'success');
      showToast(`Synchronized ${appState.lyricSegments.length} lyric segment(s).`, 'success');

      renderLyricsPanel();
    }
  } catch (err) {
    appState.isSyncingLyrics = false;
    if (btnSync) btnSync.removeAttribute('disabled');
    if (syncBadge) syncBadge.textContent = 'Sync Failed';

    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Failed to sync lyrics from transcript.';
    window.pipelineController.updatePipelineStage(10, 'failed', `Lyric sync failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Lyric Sync Error] ${safeErrorMsg}`, 'error');
    showToast(`Lyric sync error: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Loads project lyrics, styles, animations, and preview history
 * @param {string} projectId 
 */
async function loadLyrics(projectId) {
  if (!projectId) return;

  try {
    const res = await getLyricsAPI(projectId);
    if (res && res.success) {
      appState.lyricSegments = res.segments || [];
      appState.lyricStyles = res.styles || [];
      appState.lyricAnimations = res.animations || [];
      appState.lyricPreviews = res.previews || [];

      if (appState.lyricSegments.length > 0 && (!appState.selectedLyricSegmentId || !appState.lyricSegments.some(s => s.id === appState.selectedLyricSegmentId))) {
        appState.selectedLyricSegmentId = appState.lyricSegments[0].id;
      }

      renderLyricsPanel();
    }
  } catch (e) {
    // Project may not have initialized lyrics yet; non-blocking
  }
}

/**
 * Selects a specific lyric segment for editing and updates inspector controls
 * @param {string} segmentId 
 */
function selectLyricSegment(segmentId) {
  appState.selectedLyricSegmentId = segmentId;
  renderLyricTimelineStrip();
  renderLyricEditor();
}

/**
 * Updates properties of the active lyric segment via API
 * @param {Object} updatedFields 
 */
async function updateActiveLyricSegment(updatedFields = {}) {
  if (!appState.projectId || !appState.selectedLyricSegmentId) return;

  try {
    const updated = await updateLyricSegmentAPI(appState.projectId, appState.selectedLyricSegmentId, updatedFields);
    if (updated && updated.id) {
      const idx = appState.lyricSegments.findIndex(s => s.id === updated.id);
      if (idx !== -1) {
        appState.lyricSegments[idx] = updated;
      }
    }
  } catch (err) {
    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Update failed.';
    showToast(`Failed to update segment: ${safeErrorMsg}`, 'warning');
  }
}

/**
 * Triggers rendering of a Text-Behind-Character preview frame via FastAPI
 * @param {string} projectId 
 * @param {Object} options 
 */
async function triggerLyricPreview(projectId, options = {}) {
  if (!projectId) return;

  const btnTrigger = document.getElementById('btn-trigger-lyric-preview');
  const statusBox = document.getElementById('lyric-preview-status-box');
  const statusTitle = document.getElementById('lyric-status-title');
  const statusSub = document.getElementById('lyric-status-sub');

  appState.isCompositingLyrics = true;
  if (btnTrigger) btnTrigger.setAttribute('disabled', 'true');

  if (statusBox) {
    statusBox.style.display = 'flex';
    statusBox.classList.remove('is-failed', 'is-completed');
  }
  if (statusTitle) statusTitle.textContent = 'Compositing text behind character...';
  if (statusSub) statusSub.textContent = 'Applying soft alpha occlusion & motion typography...';

  window.pipelineController.updatePipelineStage(10, 'processing', 'Compositing kinetic typography behind foreground character...');
  window.pipelineController.updateStatus(`[Text Behind Character] Rendering composite preview frame for project ${projectId.substring(0, 8)}...`, 'info');

  try {
    const res = await previewLyricCompositeAPI(projectId, options);
    if (res && res.success && res.preview) {
      const preview = res.preview;
      appState.currentLyricPreview = preview;

      // Add or replace in preview history
      const existingIdx = appState.lyricPreviews.findIndex(p => p.id === preview.id);
      if (existingIdx !== -1) {
        appState.lyricPreviews[existingIdx] = preview;
      } else {
        appState.lyricPreviews.unshift(preview);
      }

      appState.isCompositingLyrics = false;
      if (btnTrigger) btnTrigger.removeAttribute('disabled');

      if (statusBox) statusBox.classList.add('is-completed');
      if (statusTitle) statusTitle.textContent = 'Text-Behind-Character composite ready.';
      if (statusSub) statusSub.textContent = `Timestamp: ${formatTimestampSeconds(preview.timestamp)} | Style: ${preview.style_name || 'Bold Cinematic'}`;

      window.pipelineController.updatePipelineStage(10, 'completed', 'Kinetic text layered behind foreground character.');
      window.pipelineController.updateStatus(
        `[Layered Composite Complete] Text successfully occluded behind primary character at t=${formatTimestampSeconds(preview.timestamp)}.`,
        'success'
      );
      showToast('Text-Behind-Character composite preview rendered.', 'success');

      renderLyricPreviews();
    }
  } catch (err) {
    appState.isCompositingLyrics = false;
    if (btnTrigger) btnTrigger.removeAttribute('disabled');

    const safeErrorMsg = err?.data?.error?.message || err?.message || 'Lyric preview failed.';
    if (statusBox) statusBox.classList.add('is-failed');
    if (statusTitle) statusTitle.textContent = `Lyric composite preview failed: ${safeErrorMsg}`;
    if (statusSub) statusSub.textContent = 'Ensure foreground segmentation has been executed first.';

    window.pipelineController.updatePipelineStage(10, 'failed', `Lyric composite failed: ${safeErrorMsg}`);
    window.pipelineController.updateStatus(`[Lyric Composite Error] ${safeErrorMsg}`, 'error');
    showToast(`Lyric preview failed: ${safeErrorMsg}`, 'error');
  }
}

/**
 * Renders the entire Kinetic Lyrics tab panel (timeline, editor, previews)
 */
function renderLyricsPanel() {
  renderLyricTimelineStrip();
  renderLyricEditor();
  renderLyricPreviews();
}

/**
 * Renders the interactive timeline strip of lyric segments
 */
function renderLyricTimelineStrip() {
  const container = document.getElementById('lyric-timeline-strip');
  const countBadge = document.getElementById('val-lyrics-segments-count');

  if (countBadge) {
    countBadge.textContent = `${appState.lyricSegments.length} Segment${appState.lyricSegments.length === 1 ? '' : 's'}`;
  }

  if (!container) return;

  if (appState.lyricSegments.length === 0) {
    container.innerHTML = `
      <div class="scenes-empty-placeholder">
        Timeline segments will appear here. Click 'Sync from Transcript' to initialize.
      </div>
    `;
    return;
  }

  container.innerHTML = '';

  appState.lyricSegments.forEach((seg, idx) => {
    const pill = document.createElement('div');
    const isSelected = seg.id === appState.selectedLyricSegmentId;
    pill.className = `lyric-timeline-pill ${isSelected ? 'active' : ''}`;

    const seqStr = String((seg.sequence !== undefined ? seg.sequence : idx) + 1).padStart(2, '0');
    const startTimeStr = formatTimestampSeconds(seg.start_time || 0);
    const endTimeStr = formatTimestampSeconds(seg.end_time || 0);
    const textPreview = escapeHtmlString(seg.text || '(Empty segment)');

    pill.innerHTML = `
      <div class="lyric-pill-left">
        <span class="lyric-pill-seq">#${seqStr}</span>
        <span class="lyric-pill-text">${textPreview}</span>
      </div>
      <div class="lyric-pill-right">
        <span class="lyric-pill-time">${startTimeStr} - ${endTimeStr}</span>
      </div>
    `;

    pill.addEventListener('click', () => {
      selectLyricSegment(seg.id);
    });

    container.appendChild(pill);
  });
}

/**
 * Populates the Active Lyric Segment Editor with currently selected segment parameters
 */
function renderLyricEditor() {
  const editorCard = document.getElementById('lyric-editor-container');
  if (!editorCard) return;

  const activeSeg = appState.lyricSegments.find(s => s.id === appState.selectedLyricSegmentId);
  if (!activeSeg) {
    editorCard.style.display = 'none';
    return;
  }

  editorCard.style.display = 'flex';

  const timeTag = document.getElementById('val-lyric-time-tag');
  const inputText = document.getElementById('input-lyric-segment-text');
  const selectStyle = document.getElementById('select-lyric-style');
  const tagStyle = document.getElementById('val-lyric-style-name');
  const selectAnim = document.getElementById('select-lyric-animation');
  const tagAnim = document.getElementById('val-lyric-anim-name');
  const sliderPosY = document.getElementById('slider-lyric-pos-y');
  const tagPosY = document.getElementById('val-lyric-pos-y');
  const sliderPosX = document.getElementById('slider-lyric-pos-x');
  const tagPosX = document.getElementById('val-lyric-pos-x');
  const sliderScale = document.getElementById('slider-lyric-scale');
  const tagScale = document.getElementById('val-lyric-scale');
  const sliderOpacity = document.getElementById('slider-lyric-opacity');
  const tagOpacity = document.getElementById('val-lyric-opacity');

  if (timeTag) {
    timeTag.textContent = `${formatTimestampSeconds(activeSeg.start_time || 0)} - ${formatTimestampSeconds(activeSeg.end_time || 0)}`;
  }

  if (inputText) {
    inputText.value = activeSeg.text || '';
  }

  // Match Style
  if (selectStyle) {
    const matchedStyle = appState.lyricStyles.find(s => s.id === activeSeg.style_id);
    if (matchedStyle && Array.from(selectStyle.options).some(o => o.value === matchedStyle.name)) {
      selectStyle.value = matchedStyle.name;
      if (tagStyle) tagStyle.textContent = selectStyle.options[selectStyle.selectedIndex].text.split(':')[1]?.trim() || matchedStyle.name;
    }
  }

  // Match Animation
  if (selectAnim) {
    const matchedAnim = appState.lyricAnimations.find(a => a.id === activeSeg.animation_id);
    if (matchedAnim && Array.from(selectAnim.options).some(o => o.value === matchedAnim.animation_type)) {
      selectAnim.value = matchedAnim.animation_type;
      if (tagAnim) tagAnim.textContent = selectAnim.options[selectAnim.selectedIndex].text.split('—')[0]?.trim() || matchedAnim.animation_type;
    }
  }

  // Match Position Y
  const posY = activeSeg.position_y !== undefined ? activeSeg.position_y : 0.75;
  if (sliderPosY) sliderPosY.value = posY;
  if (tagPosY) tagPosY.textContent = `${Math.round(posY * 100)}% (Vertical Anchor)`;

  // Match Position X
  const posX = activeSeg.position_x !== undefined ? activeSeg.position_x : 0.5;
  if (sliderPosX) sliderPosX.value = posX;
  if (tagPosX) tagPosX.textContent = `${Math.round(posX * 100)}% (Center)`;

  // Match Scale
  const scale = activeSeg.scale !== undefined ? activeSeg.scale : 1.0;
  if (sliderScale) sliderScale.value = scale;
  if (tagScale) tagScale.textContent = `${scale.toFixed(1)}x`;

  // Match Opacity
  const opacity = activeSeg.opacity !== undefined ? activeSeg.opacity : 1.0;
  if (sliderOpacity) sliderOpacity.value = opacity;
  if (tagOpacity) tagOpacity.textContent = `${Math.round(opacity * 100)}%`;
}

/**
 * Renders Text-Behind-Character Before/After composite preview cards
 */
function renderLyricPreviews() {
  const container = document.getElementById('lyric-previews-container');
  const countBadge = document.getElementById('val-lyric-previews-count');

  if (countBadge) {
    countBadge.textContent = `${appState.lyricPreviews.length} Preview${appState.lyricPreviews.length === 1 ? '' : 's'}`;
  }

  if (!container) return;

  if (appState.lyricPreviews.length === 0) {
    container.innerHTML = `
      <div class="scenes-empty-placeholder">
        Text-Behind-Character composite previews will appear here. Click 'Composite &amp; Preview Text Behind Character' above.
      </div>
    `;
    return;
  }

  container.innerHTML = '';

  appState.lyricPreviews.forEach((preview, idx) => {
    const card = document.createElement('div');
    card.className = 'lyric-preview-card';

    const timeFormatted = formatTimestampSeconds(preview.timestamp || 0);
    const textSnippet = escapeHtmlString(preview.text_rendered || '');
    const styleName = escapeHtmlString(preview.style_name || 'Bold Cinematic');
    const animType = escapeHtmlString(preview.animation_type || 'POP');

    // Output composite media URL
    const compUrl = preview.output_media_file_id
      ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(preview.output_media_file_id)}/file`
      : '';

    // Matched background/original for Before view if available in segmentation
    const matchedSeg = appState.segmentationResults.find(s => s.id === preview.segmentation_id) || appState.segmentationResults[0];
    const beforeUrl = matchedSeg && matchedSeg.composite_media_file_id
      ? `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(matchedSeg.composite_media_file_id)}/file`
      : compUrl;

    card.innerHTML = `
      <div class="lyric-preview-card-header">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="badge badge-cyan">t=${timeFormatted}</span>
          <span style="font-weight: 600; color: var(--text-primary); font-size: 11px;">"${textSnippet}"</span>
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
          <span class="badge badge-optional" style="font-size: 10px;">${styleName}</span>
          <span class="badge badge-cyan" style="font-size: 10px;">${animType}</span>
        </div>
      </div>

      <div class="lyric-before-after-grid">
        <!-- Before: Without Text -->
        <div class="lyric-preview-pane">
          <div class="lyric-preview-pane-label">
            <span>Before: Foreground Subject</span>
          </div>
          <img class="lyric-preview-thumb" src="${beforeUrl}" alt="Before Text" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Character</span>'">
        </div>

        <!-- After: Kinetic Text Behind Character -->
        <div class="lyric-preview-pane">
          <div class="lyric-preview-pane-label">
            <span style="color: var(--cyber-cyan);">After: Text Behind Character</span>
          </div>
          <img class="lyric-preview-thumb" src="${compUrl}" alt="Text Behind Character Composite" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'text-muted font-mono\\' style=\\'font-size:10px;\\'>Composite</span>'">
        </div>
      </div>

      <div class="layer-metrics-bar" style="margin-top: 4px;">
        <span class="metric-chip">Z-Order: <strong class="text-cyan">BG → TEXT → FG</strong></span>
        <span class="metric-chip">Occlusion: <strong class="text-cyan">Soft Alpha Mask</strong></span>
        <button class="btn-regen-frame btn-regen-lyric" data-preview-id="${preview.id}" style="margin-left: auto;" title="Re-composite at this timestamp">⚡ Re-render</button>
      </div>
    `;

    // Bind re-render
    const reRenderBtn = card.querySelector('.btn-regen-lyric');
    if (reRenderBtn) {
      reRenderBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await triggerLyricPreview(appState.projectId, {
          lyric_segment_id: preview.lyric_segment_id,
          timestamp: preview.timestamp,
        });
      });
    }

    container.appendChild(card);
  });
}

/* ===================================================================
   PHASE 13: FINAL 9:16 REEL RENDER & VIDEO PLAYBACK ORCHESTRATION
   =================================================================== */

/**
 * Initializes Final Reel Render UI controls, options, and actions
 */
function initRenderControls() {
  const btnTriggerRender = document.getElementById('btn-trigger-final-render');
  const btnCancelRender = document.getElementById('btn-cancel-final-render');
  const btnGenReelTop = document.getElementById('btn-generate-reel');

  if (btnTriggerRender) {
    btnTriggerRender.addEventListener('click', async () => {
      const audioChk = document.getElementById('chk-render-audio');
      const lyricsChk = document.getElementById('chk-render-lyrics');
      const forceChk = document.getElementById('chk-render-force');

      const options = {
        output_width: 1080,
        output_height: 1920,
        fps: (appState.videoMetadata && appState.videoMetadata.fps) || 30.0,
        video_codec: 'libx264',
        audio_codec: 'aac',
        include_audio: audioChk ? audioChk.checked : true,
        include_lyrics: lyricsChk ? lyricsChk.checked : true,
        force_rerender: forceChk ? forceChk.checked : false,
      };

      await triggerFinalRender(appState.projectId, options);
    });
  }

  if (btnCancelRender) {
    btnCancelRender.addEventListener('click', async () => {
      if (appState.currentRenderJob && appState.currentRenderJob.id) {
        await cancelActiveRender(appState.projectId, appState.currentRenderJob.id);
      }
    });
  }

  // Override top Generate Reel button to switch to Output tab and trigger render
  if (btnGenReelTop) {
    btnGenReelTop.addEventListener('click', async (e) => {
      e.preventDefault();
      // Activate output tab
      const outputTabBtn = document.querySelector('.inspector-tabs .tab-btn[data-tab="output"]');
      if (outputTabBtn) {
        outputTabBtn.click();
      }
      showToast('Switched to Output & Final Reel Render panel', 'info');
    });
  }
}

/**
 * Triggers full 9:16 final Reel render pipeline via FastAPI backend
 * @param {string} projectId 
 * @param {Object} options 
 */
async function triggerFinalRender(projectId, options = {}) {
  const cleanProjId = (projectId || appState.projectId || '').trim();
  if (!cleanProjId) {
    showToast('No active project found. Please upload a source video first.', 'warning');
    return;
  }

  const statusBox = document.getElementById('final-render-status-box');
  const statusTitle = document.getElementById('final-render-status-title');
  const statusSub = document.getElementById('final-render-status-sub');
  const statusPercent = document.getElementById('final-render-status-percent');
  const progressBar = document.getElementById('final-render-progress-bar');
  const btnTrigger = document.getElementById('btn-trigger-final-render');
  const btnCancel = document.getElementById('btn-cancel-final-render');
  const badgeStatus = document.getElementById('val-render-status-badge');

  appState.isRendering = true;
  if (btnTrigger) btnTrigger.disabled = true;
  if (btnCancel) btnCancel.style.display = 'inline-flex';
  if (statusBox) statusBox.style.display = 'flex';
  if (badgeStatus) {
    badgeStatus.textContent = 'Rendering...';
    badgeStatus.className = 'badge badge-cyan';
  }

  // Update pipeline node 11 to active
  updatePipelineStage(11, 'active', 'Compositing 3D Comic Reel...');
  updateStatus(`[PHASE 13] Starting final 9:16 Reel render for project ${cleanProjId}...`, 'info');

  if (statusTitle) statusTitle.textContent = 'Preparing final render...';
  if (statusSub) statusSub.textContent = 'Analyzing source timing and discovering visual layers...';
  if (statusPercent) statusPercent.textContent = '10%';
  if (progressBar) progressBar.style.width = '10%';

  try {
    const res = await renderProjectReelAPI(cleanProjId, options);
    if (res && res.job) {
      appState.currentRenderJob = res.job;

      // Update progress and stages
      if (statusPercent) statusPercent.textContent = '100%';
      if (progressBar) progressBar.style.width = '100%';
      if (statusTitle) statusTitle.textContent = 'Render complete.';
      if (statusSub) statusSub.textContent = `Generated 1080×1920 MP4 (${res.job.duration ? res.job.duration.toFixed(1) : '3.0'}s) ready for Reel playback.`;
      if (badgeStatus) {
        badgeStatus.textContent = 'Completed';
        badgeStatus.className = 'badge badge-cyan';
      }

      updatePipelineStage(11, 'completed', 'Final 9:16 Reel Ready');
      updateStatus(`[PHASE 13] Final Reel render succeeded: ${res.job.width}x${res.job.height} @ ${res.job.fps}fps H.264/AAC.`, 'success');
      showToast('🎉 Final 9:16 Comic Reel rendered successfully!', 'success');

      // Update preview video player
      updateRenderPanelUI(res.job);
      await loadRenderJobs(cleanProjId);
    } else {
      throw new Error('Unexpected render response format.');
    }
  } catch (err) {
    const errorMsg = err.message || 'Render failed.';
    if (statusTitle) statusTitle.textContent = `Render failed: ${errorMsg}`;
    if (statusSub) statusSub.textContent = 'Please check source video, scenes, and comic assets.';
    if (badgeStatus) {
      badgeStatus.textContent = 'Failed';
      badgeStatus.className = 'badge badge-optional';
    }

    updatePipelineStage(11, 'error', `Render error: ${errorMsg}`);
    updateStatus(`[PHASE 13] Render failed: ${errorMsg}`, 'error');
    showToast(`Render failed: ${errorMsg}`, 'error');
  } finally {
    appState.isRendering = false;
    if (btnTrigger) btnTrigger.disabled = false;
    if (btnCancel) btnCancel.style.display = 'none';
  }
}

/**
 * Requests cancellation of an in-progress render job
 * @param {string} projectId 
 * @param {string} renderId 
 */
async function cancelActiveRender(projectId, renderId) {
  try {
    showToast('Cancelling render job...', 'info');
    await cancelRenderJobAPI(projectId, renderId);
    showToast('Render job cancelled.', 'warning');
    updatePipelineStage(11, 'pending', 'Render cancelled');
    updateStatus(`[PHASE 13] Render job ${renderId} cancelled by user.`, 'warning');
    
    const statusTitle = document.getElementById('final-render-status-title');
    const statusSub = document.getElementById('final-render-status-sub');
    if (statusTitle) statusTitle.textContent = 'Render cancelled.';
    if (statusSub) statusSub.textContent = 'The render task was safely aborted.';
  } catch (err) {
    showToast(`Failed to cancel render: ${err.message}`, 'error');
  }
}

/**
 * Loads list of render jobs for active project
 * @param {string} projectId 
 */
async function loadRenderJobs(projectId) {
  const cleanProjId = (projectId || appState.projectId || '').trim();
  if (!cleanProjId) return;

  try {
    const res = await listRenderJobsAPI(cleanProjId);
    if (res && res.jobs) {
      appState.renderJobs = res.jobs;
      if (res.latest_render && !appState.currentRenderJob) {
        appState.currentRenderJob = res.latest_render;
        updateRenderPanelUI(res.latest_render);
      }
      renderJobsHistoryList();
    }
  } catch (err) {
    // Non-intrusive error handling
  }
}

/**
 * Updates Output Panel with active render job metadata, video player, and download link
 * @param {Object} renderJob 
 */
function updateRenderPanelUI(renderJob) {
  if (!renderJob) return;

  const player = document.getElementById('final-reel-player');
  const emptyState = document.getElementById('reel-player-empty-state');
  const downloadContainer = document.getElementById('reel-download-container');
  const downloadBtn = document.getElementById('btn-download-final-reel');
  const durationTag = document.getElementById('val-render-duration');
  const fpsTag = document.getElementById('val-render-fps');
  const badgeStatus = document.getElementById('val-render-status-badge');

  if (renderJob.fps && fpsTag) {
    fpsTag.textContent = `${Math.round(renderJob.fps)} FPS`;
  }
  if (renderJob.duration && durationTag) {
    durationTag.textContent = `${renderJob.duration.toFixed(1)}s`;
  }

  if (renderJob.status === 'completed' && renderJob.output_media_file_id) {
    const mediaUrl = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(appState.projectId)}/media/${encodeURIComponent(renderJob.output_media_file_id)}/file`;

    if (player) {
      player.src = mediaUrl;
      player.style.display = 'block';
      player.load();
    }
    if (emptyState) {
      emptyState.style.display = 'none';
    }
    if (downloadContainer) {
      downloadContainer.style.display = 'block';
    }
    if (downloadBtn) {
      downloadBtn.href = mediaUrl;
      downloadBtn.setAttribute('download', `${appState.projectId}_3D_Reel.mp4`);
    }
    if (badgeStatus) {
      badgeStatus.textContent = '1080×1920 MP4 Ready';
      badgeStatus.className = 'badge badge-cyan';
    }
  }
}

/**
 * Renders the list of previous render jobs in Output tab
 */
function renderJobsHistoryList() {
  const container = document.getElementById('render-jobs-history-container');
  const countBadge = document.getElementById('val-render-jobs-count');
  if (!container) return;

  if (countBadge) {
    countBadge.textContent = `${appState.renderJobs.length} Jobs`;
  }

  if (appState.renderJobs.length === 0) {
    container.innerHTML = '<div class="scenes-empty-placeholder">Render history will appear here once rendering is initiated.</div>';
    return;
  }

  container.innerHTML = '';
  appState.renderJobs.forEach((job) => {
    const card = document.createElement('div');
    const isCurrent = appState.currentRenderJob && appState.currentRenderJob.id === job.id;
    card.className = `render-job-card ${isCurrent ? 'active' : ''}`;

    const createdTime = job.created_at ? new Date(job.created_at).toLocaleTimeString() : '--:--';
    const statusBadgeClass = job.status === 'completed' ? 'badge-cyan' : (job.status === 'failed' ? 'badge-optional' : 'badge-cyan');

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 600; color: var(--text-primary);">${job.width}×${job.height} @ ${job.fps}fps</span>
        <span class="badge ${statusBadgeClass}">${job.status.toUpperCase()}</span>
      </div>
      <div style="display: flex; justify-content: space-between; color: var(--text-secondary); font-size: 10px;">
        <span>${job.video_codec} / ${job.audio_codec}</span>
        <span>${job.duration ? job.duration.toFixed(1) + 's' : ''} • ${createdTime}</span>
      </div>
    `;

    if (job.status === 'completed' && job.output_media_file_id) {
      card.style.cursor = 'pointer';
      card.title = 'Click to preview this render in player';
      card.addEventListener('click', () => {
        appState.currentRenderJob = job;
        updateRenderPanelUI(job);
        renderJobsHistoryList();
      });
    }

    container.appendChild(card);
  });
}

/* ===================================================================
   PHASE 16: USER AUTHENTICATION & MULTI-USER ISOLATION CONTROLLER
   =================================================================== */

let authMode = 'login'; // 'login' | 'register'

/**
 * Initializes Authentication UI, Event Listeners, and Session State
 */
function initAuthControls() {
  const userProfileWidget = document.getElementById('user-profile-widget');
  const userEmailDisplay = document.getElementById('user-email-display');
  const userAvatarBadge = document.getElementById('user-avatar-badge');
  const btnAuthAction = document.getElementById('btn-auth-action');

  const modalAuth = document.getElementById('modal-auth');
  const btnCloseAuthModal = document.getElementById('btn-auth-modal-close');
  const tabLogin = document.getElementById('tab-auth-login');
  const tabRegister = document.getElementById('tab-auth-register');
  const btnToggleMode = document.getElementById('btn-toggle-auth-mode');
  const authForm = document.getElementById('auth-form');
  const emailInput = document.getElementById('auth-email-input');
  const passwordInput = document.getElementById('auth-password-input');
  const passwordHint = document.getElementById('auth-password-hint');
  const alertBanner = document.getElementById('auth-alert-banner');
  const alertText = document.getElementById('auth-alert-text');
  const btnSubmit = document.getElementById('btn-auth-submit');
  const btnSubmitText = document.getElementById('btn-auth-submit-text');
  const headerText = document.getElementById('auth-modal-header-text');
  const togglePromptText = document.getElementById('auth-toggle-prompt-text');

  function updateAuthHeaderUI(user) {
    if (user && user.email) {
      if (userEmailDisplay) userEmailDisplay.textContent = user.email;
      if (userAvatarBadge) {
        const initials = (user.email.split('@')[0].slice(0, 2) || 'US').toUpperCase();
        userAvatarBadge.textContent = initials;
      }
      if (btnAuthAction) {
        btnAuthAction.textContent = 'Sign Out';
        btnAuthAction.className = 'btn-auth-nav btn-signed-in';
        btnAuthAction.title = `Signed in as ${user.email}. Click to Sign Out.`;
      }
    } else {
      if (userEmailDisplay) userEmailDisplay.textContent = 'Guest';
      if (userAvatarBadge) userAvatarBadge.textContent = '👤';
      if (btnAuthAction) {
        btnAuthAction.textContent = 'Sign In';
        btnAuthAction.className = 'btn-auth-nav';
        btnAuthAction.title = 'Sign In or Create Account';
      }
    }
  }

  function setAuthModalMode(mode) {
    authMode = mode;
    if (alertBanner) alertBanner.style.display = 'none';

    if (mode === 'login') {
      if (tabLogin) tabLogin.classList.add('active');
      if (tabRegister) tabRegister.classList.remove('active');
      if (headerText) headerText.textContent = 'Welcome Back';
      if (btnSubmitText) btnSubmitText.textContent = 'Sign In';
      if (passwordHint) passwordHint.style.display = 'none';
      if (togglePromptText) togglePromptText.textContent = "Don't have an account?";
      if (btnToggleMode) btnToggleMode.textContent = 'Create an Account';
    } else {
      if (tabLogin) tabLogin.classList.remove('active');
      if (tabRegister) tabRegister.classList.add('active');
      if (headerText) headerText.textContent = 'Create Account';
      if (btnSubmitText) btnSubmitText.textContent = 'Create Account';
      if (passwordHint) passwordHint.style.display = 'block';
      if (togglePromptText) togglePromptText.textContent = 'Already have an account?';
      if (btnToggleMode) btnToggleMode.textContent = 'Sign In';
    }
  }

  function showAuthModal(mode = 'login') {
    setAuthModalMode(mode);
    if (modalAuth) modalAuth.style.display = 'flex';
    if (emailInput) setTimeout(() => emailInput.focus(), 100);
  }

  function hideAuthModal() {
    if (modalAuth) modalAuth.style.display = 'none';
    if (alertBanner) alertBanner.style.display = 'none';
  }

  function showAuthError(msg) {
    if (alertBanner && alertText) {
      alertText.textContent = msg || 'Authentication error. Please try again.';
      alertBanner.className = 'auth-alert-banner';
      alertBanner.style.display = 'flex';
    }
  }

  // Initial user check
  const storedToken = typeof getAuthToken === 'function' ? getAuthToken() : null;
  const storedUser = typeof getStoredUser === 'function' ? getStoredUser() : null;

  if (storedUser) {
    updateAuthHeaderUI(storedUser);
  }

  if (storedToken && typeof apiGetMe === 'function') {
    apiGetMe().then((res) => {
      if (res?.user) {
        updateAuthHeaderUI(res.user);
      }
    }).catch(() => {
      updateAuthHeaderUI(null);
    });
  }

  // Handle header Auth Button
  if (btnAuthAction) {
    btnAuthAction.addEventListener('click', async () => {
      if (typeof isAuthenticated === 'function' && isAuthenticated()) {
        const confirmed = confirm('Are you sure you want to sign out of 3D REEL STUDIO?');
        if (confirmed) {
          await apiLogout();
          updateAuthHeaderUI(null);
          showToast('Signed out successfully.', 'info');
          if (window.pipelineController) {
            window.pipelineController.updateStatus('[Auth] Signed out.', 'info');
          }
        }
      } else {
        showAuthModal('login');
      }
    });
  }

  // Modal controls
  if (tabLogin) tabLogin.addEventListener('click', () => setAuthModalMode('login'));
  if (tabRegister) tabRegister.addEventListener('click', () => setAuthModalMode('register'));
  if (btnToggleMode) btnToggleMode.addEventListener('click', () => {
    setAuthModalMode(authMode === 'login' ? 'register' : 'login');
  });
  if (btnCloseAuthModal) btnCloseAuthModal.addEventListener('click', hideAuthModal);

  // Form submission
  if (authForm) {
    authForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = emailInput?.value?.trim();
      const password = passwordInput?.value;

      if (!email || !password) {
        showAuthError('Please enter both email and password.');
        return;
      }

      if (authMode === 'register' && password.length < 8) {
        showAuthError('Password must be at least 8 characters.');
        return;
      }

      if (btnSubmit) {
        btnSubmit.disabled = true;
        if (btnSubmitText) btnSubmitText.textContent = authMode === 'login' ? 'Signing in...' : 'Creating account...';
      }

      try {
        let res;
        if (authMode === 'login') {
          res = await apiLogin(email, password);
        } else {
          res = await apiRegister(email, password);
        }

        if (res?.success) {
          updateAuthHeaderUI(res.user);
          hideAuthModal();
          showToast(authMode === 'login' ? `Welcome back, ${res.user.email}!` : 'Account created successfully!', 'success');
          
          if (emailInput) emailInput.value = '';
          if (passwordInput) passwordInput.value = '';

          // Refresh user projects list
          if (typeof fetchProjectsList === 'function') {
            fetchProjectsList();
          }
        }
      } catch (err) {
        const errorMsg = err?.data?.error?.message || err?.message || 'Authentication failed. Please check credentials.';
        showAuthError(errorMsg);
      } finally {
        if (btnSubmit) {
          btnSubmit.disabled = false;
          if (btnSubmitText) btnSubmitText.textContent = authMode === 'login' ? 'Sign In' : 'Create Account';
        }
      }
    });
  }

  // Handle unauthorized events
  window.addEventListener('auth:unauthorized', () => {
    showToast('Session expired or authentication required. Please sign in.', 'warning');
    showAuthModal('login');
  });
}




