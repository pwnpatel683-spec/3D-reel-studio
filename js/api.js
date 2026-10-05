/**
 * ===================================================================
 * 3D REEL STUDIO — API Client & Backend Connection
 * Phase 2 & Phase 3: FastAPI Backend & Project Session Persistence
 * ===================================================================
 * 
 * Centralized HTTP client communicating with the FastAPI backend service.
 * Supports automated health probing, unified error handling, 
 * project CRUD operations, and non-blocking status synchronization.
 */

// Dynamic resolution of API Base URL supporting custom window configs, meta tags, and reverse-proxy origins
function resolveApiBaseUrl() {
  if (typeof window !== "undefined") {
    if (window.API_BASE_URL && String(window.API_BASE_URL).trim()) return String(window.API_BASE_URL).trim().replace(/\/+$/, "");
    if (window.__ENV__?.API_BASE_URL && String(window.__ENV__.API_BASE_URL).trim()) return String(window.__ENV__.API_BASE_URL).trim().replace(/\/+$/, "");
  }
  if (typeof document !== "undefined") {
    const metaTag = document.querySelector('meta[name="api-base-url"]')?.getAttribute("content");
    if (metaTag && metaTag.trim()) return metaTag.trim().replace(/\/+$/, "");
  }
  if (typeof window !== "undefined" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1" && window.location.port !== "8080") {
    return window.location.origin.replace(/\/+$/, "");
  }
  return "http://127.0.0.1:8000";
}

const API_BASE_URL = resolveApiBaseUrl();

// -----------------------------------------------------------------------------
// Authentication Token Storage & State Management
// -----------------------------------------------------------------------------
const AUTH_TOKEN_STORAGE_KEY = 'reelstudio_access_token';
const AUTH_USER_STORAGE_KEY = 'reelstudio_current_user';

let _inMemoryAuthToken = null;
let _inMemoryAuthUser = null;

function getAuthToken() {
  if (_inMemoryAuthToken) return _inMemoryAuthToken;
  try {
    if (typeof localStorage !== 'undefined') {
      _inMemoryAuthToken = localStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    }
  } catch (e) {
    // Local storage access denied or disabled
  }
  return _inMemoryAuthToken;
}

function setAuthToken(token, user = null) {
  _inMemoryAuthToken = token || null;
  _inMemoryAuthUser = user || null;
  try {
    if (typeof localStorage !== 'undefined') {
      if (token) {
        localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
      } else {
        localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
      }
      if (user) {
        localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify(user));
      } else {
        localStorage.removeItem(AUTH_USER_STORAGE_KEY);
      }
    }
  } catch (e) {
    // Storage access exception
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:state-changed', { detail: { token, user } }));
  }
}

function clearAuthToken() {
  setAuthToken(null, null);
}

function getStoredUser() {
  if (_inMemoryAuthUser) return _inMemoryAuthUser;
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(AUTH_USER_STORAGE_KEY);
      if (raw) _inMemoryAuthUser = JSON.parse(raw);
    }
  } catch (e) {
    _inMemoryAuthUser = null;
  }
  return _inMemoryAuthUser;
}

/**
 * Reusable HTTP API request wrapper with standardized JSON error handling.
 * Automatically injects the Bearer authorization header if an access token is available.
 * @param {string} endpoint - API path (e.g. '/api/v1/health')
 * @param {Object} options - fetch options (method, headers, body, etc.)
 * @returns {Promise<any>}
 */
async function apiRequest(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
  const defaultHeaders = {
    'Accept': 'application/json',
  };

  // Inject Authorization header if user is authenticated and header not explicitly set
  const token = getAuthToken();
  if (token && !options.headers?.Authorization && !options.headers?.authorization) {
    defaultHeaders['Authorization'] = `Bearer ${token}`;
  }

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body && typeof options.body === 'object' && !isFormData) {
    defaultHeaders['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
  };

  try {
    const response = await fetch(url, config);
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      // If 401 Unauthorized occurs on a protected endpoint, notify application
      if (response.status === 401 && !endpoint.includes('/auth/login') && !endpoint.includes('/auth/register')) {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { endpoint } }));
        }
      }

      const errorMsg = data?.error?.message || `HTTP error ${response.status}: ${response.statusText}`;
      const errorObj = new Error(errorMsg);
      errorObj.status = response.status;
      errorObj.data = data;
      throw errorObj;
    }

    return data;
  } catch (error) {
    // Network failure or non-2xx status
    throw error;
  }
}

/**
 * Probes the FastAPI backend health endpoint (GET /api/v1/health)
 * and updates the studio status pill accordingly.
 * @param {boolean} [silent=false] - Whether to suppress telemetry logging
 * @returns {Promise<boolean>}
 */
async function checkBackendHealth(silent = false) {
  updateBackendStatusUI('connecting');

  try {
    const data = await apiRequest('/api/v1/health');
    if (data && data.success && data.status === 'healthy') {
      updateBackendStatusUI('connected', data);
      if (!silent && window.pipelineController) {
        window.pipelineController.updateStatus(
          `[FastAPI Online] Connected to ${data.service} v${data.version} (${API_BASE_URL})`,
          'success'
        );
      }
      return true;
    } else {
      updateBackendStatusUI('offline');
      return false;
    }
  } catch (err) {
    updateBackendStatusUI('offline');
    if (!silent && window.pipelineController) {
      window.pipelineController.updateStatus(
        `[FastAPI Standby] Backend is currently offline at ${API_BASE_URL}. Running in client studio mode.`,
        'info'
      );
    }
    return false;
  }
}

/**
 * Updates the Header System Status indicator according to backend state
 * @param {'connecting'|'connected'|'offline'} state 
 * @param {Object} [meta] - Response metadata
 */
function updateBackendStatusUI(state, meta = null) {
  const statusContainer = document.getElementById('system-status-indicator');
  const dot = document.getElementById('status-indicator-dot');
  const statusText = document.getElementById('status-indicator-text');
  const subText = document.getElementById('status-indicator-sub');

  if (!statusContainer || !dot || !statusText || !subText) return;

  if (typeof appState !== 'undefined') {
    appState.backendStatus = state;
  }

  if (state === 'connected') {
    dot.className = 'status-indicator-dot status-dot-connected';
    statusText.textContent = 'BACKEND CONNECTED';
    statusText.className = 'text-cyan font-mono';
    subText.textContent = `API: v${meta?.version || '1.0.0'}`;
    subText.className = 'text-muted font-mono';
    statusContainer.title = `Connected to ${meta?.service || '3D Reel Studio API'} (${API_BASE_URL})`;
  } else if (state === 'connecting') {
    dot.className = 'status-indicator-dot status-dot-connecting';
    statusText.textContent = 'CONNECTING...';
    statusText.className = 'text-warning font-mono';
    subText.textContent = 'API: PROBING';
    subText.className = 'text-muted font-mono';
    statusContainer.title = `Attempting connection to ${API_BASE_URL}...`;
  } else {
    dot.className = 'status-indicator-dot status-dot-offline';
    statusText.textContent = 'BACKEND OFFLINE';
    statusText.className = 'text-muted font-mono';
    subText.textContent = 'API: STANDBY';
    subText.className = 'text-muted font-mono';
    statusContainer.title = `Backend at ${API_BASE_URL} is offline (Local demo mode active)`;
  }
}

/* ===================================================================
   PHASE 3: PROJECT SESSION PERSISTENCE API CLIENT METHODS
   =================================================================== */

/**
 * Creates a new project in SQLite via FastAPI POST /api/v1/projects
 * @param {string} name - Project display name
 * @returns {Promise<Object>} Created project object
 */
async function createProjectAPI(name = "Untitled 3D Reel") {
  const res = await apiRequest('/api/v1/projects', {
    method: 'POST',
    body: { name: name.trim() || "Untitled 3D Reel" },
  });
  return res.project;
}

/**
 * Lists all projects from SQLite via FastAPI GET /api/v1/projects
 * @returns {Promise<Array>} List of project summary objects
 */
async function listProjectsAPI() {
  const res = await apiRequest('/api/v1/projects');
  return res.projects || [];
}

/**
 * Retrieves full project details by ID via FastAPI GET /api/v1/projects/{project_id}
 * @param {string} projectId 
 * @returns {Promise<Object>} Project details with media_files and transformation_jobs
 */
async function getProjectAPI(projectId) {
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}`);
  return res.project;
}

/**
 * Updates project name or status via FastAPI PATCH /api/v1/projects/{project_id}
 * @param {string} projectId 
 * @param {Object} updates - { name?: string, status?: string }
 * @returns {Promise<Object>} Updated project object
 */
async function updateProjectAPI(projectId, updates = {}) {
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    body: updates,
  });
  return res.project;
}

/* ===================================================================
   PHASE 4: MEDIA UPLOAD & SECURE STORAGE API CLIENT
   =================================================================== */

/**
 * Uploads a media file (source_video or face_reference) to a project via multipart/form-data
 * POST /api/v1/projects/{project_id}/media
 * @param {string} projectId - Target project ID
 * @param {File} file - Binary File object
 * @param {'source_video'|'face_reference'} mediaType - Media type identifier
 * @param {Function} [onProgress] - Optional upload progress callback (percent: number)
 * @returns {Promise<Object>} Upload response object containing media record
 */
async function uploadMediaAPI(projectId, file, mediaType, onProgress = null) {
  const cleanId = (projectId || '').trim();
  const url = `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(cleanId)}/media`;
  const formData = new FormData();
  formData.append('file', file);
  formData.append('media_type', mediaType);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.setRequestHeader('Accept', 'application/json');

    if (xhr.upload && typeof onProgress === 'function') {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          const percent = Math.round((e.loaded / e.total) * 100);
          onProgress(percent);
        }
      });
    }

    xhr.onload = () => {
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch (e) {
        data = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data);
      } else {
        const errorMsg = data?.error?.message || `Upload failed with HTTP ${xhr.status}: ${xhr.statusText || 'Error'}`;
        const errorObj = new Error(errorMsg);
        errorObj.status = xhr.status;
        errorObj.data = data;
        reject(errorObj);
      }
    };

    xhr.onerror = () => {
      reject(new Error(`Network error connecting to FastAPI backend at ${API_BASE_URL}`));
    };

    xhr.send(formData);
  });
}

/* ===================================================================
   PHASE 5: FFMPEG AUDIO EXTRACTION API CLIENT
   =================================================================== */

/**
 * Triggers FFmpeg audio extraction for an uploaded source video via FastAPI
 * POST /api/v1/projects/{project_id}/media/{media_id}/extract-audio
 * @param {string} projectId - Target project ID
 * @param {string} mediaId - Uploaded source video media ID
 * @returns {Promise<Object>} Extracted audio media record object
 */
async function extractAudioAPI(projectId, mediaId) {
  const cleanProjId = (projectId || '').trim();
  const cleanMediaId = (mediaId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/media/${encodeURIComponent(cleanMediaId)}/extract-audio`, {
    method: 'POST',
  });
  return res.media;
}

/* ===================================================================
   PHASE 6: AI AUDIO TRANSCRIPTION & TIMESTAMPS API CLIENT
   =================================================================== */

/**
 * Triggers AI transcription for an extracted audio media file via FastAPI
 * POST /api/v1/projects/{project_id}/media/{media_id}/transcribe
 * @param {string} projectId - Target project ID
 * @param {string} mediaId - Extracted audio media ID
 * @returns {Promise<Object>} Transcript object with detected language and timestamped segments
 */
async function transcribeAudioAPI(projectId, mediaId) {
  const cleanProjId = (projectId || '').trim();
  const cleanMediaId = (mediaId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/media/${encodeURIComponent(cleanMediaId)}/transcribe`, {
    method: 'POST',
  });
  return res.transcript;
}

/* ===================================================================
   PHASE 7: VIDEO SCENE & CONTENT ANALYSIS API CLIENT
   =================================================================== */

/**
 * Triggers video stream metadata, scene detection, and keyframe extraction via FastAPI
 * POST /api/v1/projects/{project_id}/media/{media_id}/analyze
 * @param {string} projectId - Target project ID
 * @param {string} mediaId - Uploaded source video media ID
 * @returns {Promise<Object>} Video analysis object with metadata, scenes, and keyframes
 */
async function analyzeVideoAPI(projectId, mediaId) {
  const cleanProjId = (projectId || '').trim();
  const cleanMediaId = (mediaId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/media/${encodeURIComponent(cleanMediaId)}/analyze`, {
    method: 'POST',
  });
  return res.analysis;
}

/* ===================================================================
   PHASE 8: FACE DETECTION + IDENTITY + POSE TRACKING API CLIENT
   =================================================================== */

/**
 * Triggers face detection, primary subject selection, face references, and pose tracking via FastAPI
 * POST /api/v1/projects/{project_id}/media/{media_id}/vision-analysis
 * @param {string} projectId - Target project ID
 * @param {string} mediaId - Uploaded source video media ID
 * @returns {Promise<Object>} Vision analysis detail object
 */
async function analyzeVisionAPI(projectId, mediaId) {
  const cleanProjId = (projectId || '').trim();
  const cleanMediaId = (mediaId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/media/${encodeURIComponent(cleanMediaId)}/vision-analysis`, {
    method: 'POST',
  });
  return res.analysis;
}

/* ===================================================================
   PHASE 9: 3D COMIC STYLE GENERATION API CLIENT
   =================================================================== */

/**
 * Triggers 3D Comic Frame generation for a scene or batch of scenes via FastAPI
 * POST /api/v1/projects/{project_id}/comic-generation
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { scene_id?: string, style_preset?: string, prompt_directive?: string, provider?: string, model?: string }
 * @returns {Promise<Object>} Comic generation detail response object
 */
async function generateComicAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/comic-generation`, {
    method: 'POST',
    body: options,
  });
  return res;
}

/* ===================================================================
   PHASE 10: IDENTITY + TEMPORAL CONSISTENCY API CLIENT
   =================================================================== */

/**
 * Retrieves or constructs the character consistency profile via FastAPI
 * POST /api/v1/projects/{project_id}/consistency/profile
 * @param {string} projectId - Target project ID
 * @returns {Promise<Object>} Character consistency profile object
 */
async function getConsistencyProfileAPI(projectId) {
  const cleanProjId = (projectId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/consistency/profile`, {
    method: 'POST',
  });
  return res.profile;
}

/**
 * Triggers identity-consistent and temporally chained 3D comic frame generation via FastAPI
 * POST /api/v1/projects/{project_id}/consistency/generate
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { scene_id?: string, scene_ids?: string[], style_preset?: string, prompt_override?: string, force_regenerate?: boolean }
 * @returns {Promise<Object>} Consistency generation detail response object
 */
async function generateConsistencyAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/consistency/generate`, {
    method: 'POST',
    body: options,
  });
  return res;
}

/* ===================================================================
   PHASE 11: FOREGROUND SEGMENTATION & DYNAMIC BACKGROUND API CLIENT
   =================================================================== */

/**
 * Triggers foreground character isolation, alpha matting, and dynamic background layering via FastAPI
 * POST /api/v1/projects/{project_id}/segmentation
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { consistent_frame_id?: string, consistent_frame_ids?: string[], scene_id?: string, background_mode?: string, refinement_params?: Object, force_regenerate?: boolean }
 * @returns {Promise<Object>} Segmentation response containing results list
 */
async function segmentForegroundAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  const res = await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/segmentation`, {
    method: 'POST',
    body: options,
  });
  return res;
}

/* ===================================================================
   PHASE 12: KINETIC LYRICS & TEXT-BEHIND-CHARACTER API CLIENT
   =================================================================== */

/**
 * Retrieves kinetic lyrics configuration, styles, animations, and segments via FastAPI
 * GET /api/v1/projects/{project_id}/lyrics
 * @param {string} projectId - Target project ID
 * @returns {Promise<Object>} Lyrics list response object
 */
async function getLyricsAPI(projectId) {
  const cleanProjId = (projectId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/lyrics`);
}

/**
 * Synchronizes transcript segments into editable lyric segments via FastAPI
 * POST /api/v1/projects/{project_id}/lyrics/sync
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { force_recreate?: boolean, default_style_name?: string, default_animation_name?: string }
 * @returns {Promise<Object>} Sync response with segments, styles, animations
 */
async function syncLyricsAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/lyrics/sync`, {
    method: 'POST',
    body: options,
  });
}

/**
 * Updates a specific lyric segment's styling, timing, or normalized positioning via FastAPI
 * PATCH /api/v1/projects/{project_id}/lyrics/segments/{segment_id}
 * @param {string} projectId - Target project ID
 * @param {string} segmentId - Target lyric segment ID
 * @param {Object} updatePayload - { text?: string, style_id?: string, animation_id?: string, position_x?: number, position_y?: number, scale?: number, rotation?: number, opacity?: number, enabled?: boolean }
 * @returns {Promise<Object>} Updated lyric segment object
 */
async function updateLyricSegmentAPI(projectId, segmentId, updatePayload = {}) {
  const cleanProjId = (projectId || '').trim();
  const cleanSegId = (segmentId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/lyrics/segments/${encodeURIComponent(cleanSegId)}`, {
    method: 'PATCH',
    body: updatePayload,
  });
}

/**
 * Generates a text-behind-character composite preview frame via FastAPI
 * POST /api/v1/projects/{project_id}/lyrics/preview
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { scene_id?: string, segmentation_id?: string, lyric_segment_id?: string, timestamp?: number, text_override?: string, position_x?: number, position_y?: number, scale?: number, opacity?: number, style_id?: string, animation_id?: string }
 * @returns {Promise<Object>} Preview response object containing preview detail and output media ID
 */
async function previewLyricCompositeAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/lyrics/preview`, {
    method: 'POST',
    body: options,
  });
}

/* ===================================================================
   PHASE 13: FINAL VIDEO COMPOSITING & 9:16 REEL RENDERING API CLIENT
   =================================================================== */

/**
 * Initiates final 9:16 Reel rendering for a project via FastAPI
 * POST /api/v1/projects/{project_id}/render
 * @param {string} projectId - Target project ID
 * @param {Object} [options] - { output_width?: number, output_height?: number, fps?: number, video_codec?: string, audio_codec?: string, include_audio?: boolean, include_lyrics?: boolean, force_rerender?: boolean }
 * @returns {Promise<Object>} Render job response object
 */
async function renderProjectReelAPI(projectId, options = {}) {
  const cleanProjId = (projectId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/render`, {
    method: 'POST',
    body: options,
  });
}

/**
 * Lists all render jobs associated with a project via FastAPI
 * GET /api/v1/projects/{project_id}/render
 * @param {string} projectId - Target project ID
 * @returns {Promise<Object>} Render jobs list and latest render job
 */
async function listRenderJobsAPI(projectId) {
  const cleanProjId = (projectId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/render`);
}

/**
 * Retrieves status and progress of a specific render job via FastAPI
 * GET /api/v1/projects/{project_id}/render/{render_id}
 * @param {string} projectId - Target project ID
 * @param {string} renderId - Target render job ID
 * @returns {Promise<Object>} Render job detail response object
 */
async function getRenderJobAPI(projectId, renderId) {
  const cleanProjId = (projectId || '').trim();
  const cleanRenderId = (renderId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/render/${encodeURIComponent(cleanRenderId)}`);
}

/**
 * Requests cancellation of an in-progress render job via FastAPI
 * POST /api/v1/projects/{project_id}/render/{render_id}/cancel
 * @param {string} projectId - Target project ID
 * @param {string} renderId - Target render job ID
 * @returns {Promise<Object>} Cancelled render job response
 */
async function cancelRenderJobAPI(projectId, renderId) {
  const cleanProjId = (projectId || '').trim();
  const cleanRenderId = (renderId || '').trim();
  return await apiRequest(`/api/v1/projects/${encodeURIComponent(cleanProjId)}/render/${encodeURIComponent(cleanRenderId)}/cancel`, {
    method: 'POST',
  });
}

/* ===================================================================
   PHASE 16: USER AUTHENTICATION & MULTI-USER ISOLATION API CLIENT
   =================================================================== */

/**
 * Registers a new user account with email and password
 * POST /api/v1/auth/register
 * @param {string} email
 * @param {string} password
 * @returns {Promise<Object>} Auth success response with token and safe user profile
 */
async function apiRegister(email, password) {
  const payload = { email: (email || '').trim(), password };
  const res = await apiRequest('/api/v1/auth/register', {
    method: 'POST',
    body: payload,
  });
  if (res?.success && res?.access_token) {
    setAuthToken(res.access_token, res.user);
  }
  return res;
}

/**
 * Authenticates an existing user with email and password
 * POST /api/v1/auth/login
 * @param {string} email
 * @param {string} password
 * @returns {Promise<Object>} Auth success response with token and safe user profile
 */
async function apiLogin(email, password) {
  const payload = { email: (email || '').trim(), password };
  const res = await apiRequest('/api/v1/auth/login', {
    method: 'POST',
    body: payload,
  });
  if (res?.success && res?.access_token) {
    setAuthToken(res.access_token, res.user);
  }
  return res;
}

/**
 * Retrieves the currently authenticated user's profile
 * GET /api/v1/auth/me
 * @returns {Promise<Object>} Current user profile response
 */
async function apiGetMe() {
  try {
    const res = await apiRequest('/api/v1/auth/me');
    if (res?.success && res?.user) {
      setAuthToken(getAuthToken(), res.user);
      return res;
    }
  } catch (err) {
    if (err.status === 401) {
      clearAuthToken();
    }
    throw err;
  }
  return null;
}

/**
 * Logs out the current user and clears stored session credentials
 * POST /api/v1/auth/logout
 * @returns {Promise<Object>} Logout status response
 */
async function apiLogout() {
  try {
    await apiRequest('/api/v1/auth/logout', { method: 'POST' });
  } catch (err) {
    // Ignore network error on logout
  } finally {
    clearAuthToken();
  }
  return { success: true, message: 'Logged out successfully.' };
}

/**
 * Returns true if an active authentication token exists
 * @returns {boolean}
 */
function isAuthenticated() {
  return !!getAuthToken();
}





