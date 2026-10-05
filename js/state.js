/**
 * ===================================================================
 * 3D REEL STUDIO — Central State Management
 * Phase 1 Frontend Foundation
 * ===================================================================
 * 
 * Centralized, reactive state store for studio parameters, source media,
 * pipeline status, and inspector controls.
 * Ready for clean FastAPI WebSocket / REST integration in subsequent phases.
 */

const appState = {
  // Video Source State
  videoFile: null,
  videoUrl: null,
  videoMediaId: null,
  audioMediaId: null,
  isUploadingVideo: false,
  isExtractingAudio: false,
  videoMetadata: {
    name: '',
    size: 0,
    formattedSize: '0 MB',
    duration: 0,
    formattedDuration: '00:00',
    width: 0,
    height: 0,
    type: ''
  },

  // Face Reference (Optional)
  faceReference: null,
  faceReferenceUrl: null,
  faceReferenceMediaId: null,
  isUploadingFace: false,

  // Project & Session
  projectId: 'PROJ-' + Math.random().toString(36).substring(2, 8).toUpperCase(),
  projectName: 'Default 3D Reel',
  currentStage: 'upload',
  selectedStyle: '3d-comic',
  backendStatus: 'offline',

  // Effect Controls
  effects: {
    kineticLyrics: true,
    lyricsStyle: 'cyber-pop',
    lyricsPosition: 'bottom',
    adaptiveBackground: true,
    characterMasking: false,
    motionStrength: 75,
    faceIdentityWeight: 85
  },

  // Output Preset Settings
  outputSettings: {
    aspectRatio: '9:16',
    resolution: '1080x1920',
    format: 'mp4',
    quality: 'high',
    fps: 30
  },

  // Audio Transcription State (Phase 6)
  transcriptId: null,
  language: null,
  fullText: '',
  segments: [],
  isTranscribing: false,

  // Video Scene & Content Analysis State (Phase 7)
  videoAnalysis: null,
  isAnalyzingVideo: false,

  // Face Detection, Identity & Pose Tracking State (Phase 8)
  visionAnalysis: null,
  isAnalyzingVision: false,
  visionOverlays: {
    showFaceBox: true,
    showPoseSkeleton: true,
  },

  // 3D Comic Generation State (Phase 9)
  comicGenerations: [],
  currentComicGeneration: null,
  isGeneratingComic: false,
  comicStylePreset: '3d-comic',
  selectedGenerationSceneId: 'all',

  // Identity + Temporal Consistency State (Phase 10)
  consistencyProfile: null,
  consistencyGenerations: [],
  currentConsistencyGeneration: null,
  isGeneratingConsistency: false,
  consistencyStylePreset: '3d-comic',
  selectedConsistencySceneId: 'all',

  // Foreground Segmentation & Dynamic Background State (Phase 11)
  segmentationResults: [],
  currentSegmentationResult: null,
  isSegmenting: false,
  backgroundMode: 'ORIGINAL',
  selectedSegmentationFrameId: 'all',

  // Kinetic Lyrics & Text-Behind-Character State (Phase 12)
  lyricSegments: [],
  lyricStyles: [],
  lyricAnimations: [],
  lyricPreviews: [],
  selectedLyricSegmentId: null,
  currentLyricPreview: null,
  isSyncingLyrics: false,
  isCompositingLyrics: false,

  // Final Video Compositing & 9:16 Reel Rendering State (Phase 13)
  renderJobs: [],
  currentRenderJob: null,
  isRendering: false,
  renderProgress: 0.0,
  renderStageMessage: '',



  processingStatus: {
    1: { id: 1, name: 'Upload', label: '01 Upload', status: 'ready', description: 'Source video ingestion' },
    2: { id: 2, name: 'Audio', label: '02 Audio', status: 'pending', description: 'Demux audio track' },
    3: { id: 3, name: 'Transcription', label: '03 Transcription', status: 'pending', description: 'Whisper speech-to-text' },
    4: { id: 4, name: 'Scene Analysis', label: '04 Scene Analysis', status: 'pending', description: 'Keyframe and depth map' },
    5: { id: 5, name: 'Face & Pose', label: '05 Face & Pose', status: 'pending', description: 'Landmark detection' },
    6: { id: 6, name: '3D Generation', label: '06 3D Generation', status: 'pending', description: 'Comic stylization model' },
    7: { id: 7, name: 'Identity', label: '07 Identity', status: 'pending', description: 'Face reference blending' },
    8: { id: 8, name: 'Background', label: '08 Background', status: 'pending', description: 'Environment synthesis' },
    9: { id: 9, name: 'Masking', label: '09 Masking', status: 'pending', description: 'Foreground matting' },
    10: { id: 10, name: 'Lyrics', label: '10 Lyrics', status: 'pending', description: 'Animated typography' },
    11: { id: 11, name: 'Final Render', label: '11 Final Render', status: 'pending', description: 'FFmpeg multiplexing' }
  },

  // Telemetry Log History
  logs: []
};

/**
 * Format raw bytes into human-readable format (KB, MB, GB)
 * @param {number} bytes 
 * @returns {string}
 */
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Format seconds into mm:ss
 * @param {number} seconds 
 * @returns {string}
 */
function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}
