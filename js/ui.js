/**
 * ===================================================================
 * 3D REEL STUDIO — UI Components, Modals & Toast Controller
 * Phase 1, 2 & 3: Frontend UI, Backend Sync & Project Persistence
 * ===================================================================
 */

/**
 * Global Toast Notification System
 * @param {string} message 
 * @param {'info'|'success'|'warning'|'error'} type 
 * @param {number} duration 
 */
function showToast(message, type = 'info', duration = 3500) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item toast-${type}`;

  const iconMap = {
    info: 'ℹ',
    success: '✓',
    warning: '⚠',
    error: '✕'
  };

  toast.innerHTML = `
    <div class="toast-icon">${iconMap[type] || 'ℹ'}</div>
    <div class="toast-message">${message}</div>
  `;

  container.appendChild(toast);

  // Trigger animation frame
  requestAnimationFrame(() => {
    toast.classList.add('toast-show');
  });

  setTimeout(() => {
    toast.classList.remove('toast-show');
    setTimeout(() => {
      if (toast.parentElement) toast.remove();
    }, 300);
  }, duration);
}

class UIController {
  constructor() {
    this.initModals();
    this.initTabs();
    this.initInspectorBindings();
    this.initKeyboardShortcuts();
    this.initProjectControls();
  }

  /**
   * Bind modal triggers and close buttons
   */
  initModals() {
    // Nav links modal triggers
    const navProjects = document.getElementById('nav-projects');
    const navSettings = document.getElementById('nav-settings');
    const modalBackdrops = document.querySelectorAll('.studio-modal-backdrop');

    if (navProjects) {
      navProjects.addEventListener('click', (e) => {
        e.preventDefault();
        this.openModal('modal-projects');
        this.loadProjectsListUI();
      });
    }

    if (navSettings) {
      navSettings.addEventListener('click', (e) => {
        e.preventDefault();
        this.openModal('modal-settings');
      });
    }

    // Close buttons on all modals
    document.querySelectorAll('[data-close-modal]').forEach(btn => {
      btn.addEventListener('click', () => {
        modalBackdrops.forEach(modal => modal.classList.remove('open'));
      });
    });

    // Close on clicking backdrop
    modalBackdrops.forEach(backdrop => {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) {
          backdrop.classList.remove('open');
        }
      });
    });
  }

  /**
   * Open specific modal by ID
   * @param {string} modalId 
   */
  openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.add('open');
    }
  }

  /**
   * Close specific modal by ID
   * @param {string} modalId 
   */
  closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.remove('open');
    }
  }

  /**
   * Initialize Project Management UI controls inside Projects Modal
   */
  initProjectControls() {
    const btnCreate = document.getElementById('btn-create-new-project');
    const inputName = document.getElementById('input-new-project-name');
    const btnRefresh = document.getElementById('btn-refresh-projects');

    const handleCreate = async () => {
      const name = (inputName?.value || '').trim();
      if (!name) {
        showToast('Please enter a project name', 'warning');
        return;
      }

      try {
        showToast('Creating project in SQLite database...', 'info');
        const project = await createProjectAPI(name);
        if (project) {
          appState.projectId = project.id;
          appState.projectName = project.name;
          if (inputName) inputName.value = '';

          if (window.pipelineController) {
            window.pipelineController.updateStatus(
              `[Project Created] "${project.name}" (${project.id}) saved to SQLite database.`,
              'success'
            );
          }

          showToast(`Project "${project.name}" created!`, 'success');
          await this.loadProjectsListUI();
        }
      } catch (err) {
        showToast(`Failed to create project: ${err.message}`, 'error');
      }
    };

    if (btnCreate) {
      btnCreate.addEventListener('click', handleCreate);
    }
    if (inputName) {
      inputName.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          handleCreate();
        }
      });
    }
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => this.loadProjectsListUI());
    }
  }

  /**
   * Loads projects list from SQLite API and renders cards into modal container
   */
  async loadProjectsListUI() {
    const listContainer = document.getElementById('projects-list-container');
    const activeProjectLabel = document.getElementById('modal-active-project');
    if (activeProjectLabel && appState.projectId) {
      activeProjectLabel.textContent = `${appState.projectName || 'Active Session'} (${appState.projectId})`;
    }

    if (!listContainer) return;

    listContainer.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 16px; font-size: 12px;">Fetching projects from SQLite...</div>';

    try {
      const projects = await listProjectsAPI();
      if (!projects || projects.length === 0) {
        listContainer.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 20px; font-size: 12px;">No saved projects found in SQLite database. Create one above!</div>';
        return;
      }

      listContainer.innerHTML = '';
      projects.forEach(p => {
        const card = document.createElement('div');
        const isActive = p.id === appState.projectId;
        card.className = `project-item-card ${isActive ? 'active' : ''}`;
        
        let dateStr = 'Recently';
        try {
          dateStr = new Date(p.created_at).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
          });
        } catch (e) {}

        const statusBadgeClass = p.status === 'completed' ? 'badge-cyan' : p.status === 'processing' ? 'badge-red' : 'badge-optional';

        card.innerHTML = `
          <div class="project-card-left">
            <div class="project-card-title">
              <span>${this.escapeHtml(p.name)}</span>
              <span class="badge ${statusBadgeClass}">${p.status}</span>
            </div>
            <div class="project-card-meta">
              <span class="text-cyan font-mono">${p.id}</span>
              <span>•</span>
              <span>${dateStr}</span>
            </div>
          </div>
          <div class="project-card-actions">
            ${isActive 
              ? '<span class="badge badge-cyan" style="padding: 5px 10px;">ACTIVE</span>' 
              : `<button type="button" class="btn-open-proj" data-open-id="${p.id}">Open</button>`
            }
          </div>
        `;
        listContainer.appendChild(card);
      });

      // Bind open buttons
      listContainer.querySelectorAll('[data-open-id]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const pid = btn.getAttribute('data-open-id');
          await this.openProjectById(pid);
        });
      });
    } catch (err) {
      listContainer.innerHTML = `
        <div style="text-align: center; color: var(--neon-red); padding: 16px; font-size: 12px;">
          Failed to load projects: ${err.message || 'Backend offline'}.
        </div>
      `;
    }
  }

  /**
   * Opens a project by ID, restores state and notifies studio
   * @param {string} projectId 
   */
  async openProjectById(projectId) {
    try {
      showToast(`Loading project ${projectId}...`, 'info');
      const project = await getProjectAPI(projectId);
      if (project) {
        appState.projectId = project.id;
        appState.projectName = project.name;

        // Restore media IDs if present
        if (project.media_files && project.media_files.length > 0) {
          const videoMedia = project.media_files.find(m => m.file_type === 'source_video');
          if (videoMedia) appState.videoMediaId = videoMedia.id;
          const audioMedia = project.media_files.find(m => m.file_type === 'extracted_audio');
          if (audioMedia) appState.audioMediaId = audioMedia.id;
        }

        // Restore transcript if present
        if (project.transcripts && project.transcripts.length > 0) {
          const latestTranscript = project.transcripts[project.transcripts.length - 1];
          appState.transcriptId = latestTranscript.id;
          appState.language = latestTranscript.language;
          appState.fullText = latestTranscript.full_text;
          appState.segments = latestTranscript.segments || [];
          if (typeof renderTranscriptPanel === 'function') {
            renderTranscriptPanel(latestTranscript);
          }
          if (window.pipelineController) {
            window.pipelineController.updatePipelineStage(3, 'completed', 'Transcription loaded from project.');
          }
        }

        // Restore video analysis if present
        if (project.video_analyses && project.video_analyses.length > 0) {
          const latestAnalysis = project.video_analyses[project.video_analyses.length - 1];
          appState.videoAnalysis = latestAnalysis;
          if (typeof renderSceneAnalysisPanel === 'function') {
            renderSceneAnalysisPanel(latestAnalysis);
          }
          if (window.pipelineController) {
            window.pipelineController.updatePipelineStage(4, 'completed', 'Scene analysis loaded from project.');
          }
        }

        // Restore vision & pose analysis if present (Phase 8)
        if (project.vision_analyses && project.vision_analyses.length > 0) {
          const latestVision = project.vision_analyses[project.vision_analyses.length - 1];
          appState.visionAnalysis = latestVision;
          if (typeof renderVisionPanel === 'function') {
            renderVisionPanel(latestVision);
          }
          if (window.pipelineController) {
            window.pipelineController.updatePipelineStage(5, 'completed', 'Vision & pose analysis loaded from project.');
          }
        }

        // Restore 3D comic generations if present (Phase 9)
        if (project.comic_generations && project.comic_generations.length > 0) {
          appState.comicGenerations = project.comic_generations;
          const latestGen = project.comic_generations[project.comic_generations.length - 1];
          appState.currentComicGeneration = latestGen;
          if (typeof renderComicGenerationPanel === 'function') {
            renderComicGenerationPanel(latestGen);
          }
          if (window.pipelineController) {
            window.pipelineController.updatePipelineStage(6, 'completed', '3D Comic frames loaded from project.');
          }
        }

        // Restore Character Consistency Profile & Generations (Phase 10)
        if (project.consistency_profiles && project.consistency_profiles.length > 0) {
          appState.consistencyProfile = project.consistency_profiles[project.consistency_profiles.length - 1];
          if (typeof renderConsistencyProfilePreview === 'function') {
            renderConsistencyProfilePreview(appState.consistencyProfile);
          }
        }
        if (project.consistency_generations && project.consistency_generations.length > 0) {
          appState.consistencyGenerations = project.consistency_generations;
          const latestConsGen = project.consistency_generations[project.consistency_generations.length - 1];
          appState.currentConsistencyGeneration = latestConsGen;
          if (typeof renderConsistencyPanel === 'function') {
            renderConsistencyPanel(latestConsGen, appState.consistencyProfile);
          }
          if (window.pipelineController) {
            window.pipelineController.updatePipelineStage(7, 'completed', 'Consistent comic frames loaded from project.');
          }
        }
        
        if (window.pipelineController) {
          window.pipelineController.updateStatus(
            `[Project Loaded] Switched active studio project to "${project.name}" (${project.id}) [Status: ${project.status}]`,
            'success'
          );
        }
        
        showToast(`Opened project: ${project.name}`, 'success');
        this.closeModal('modal-projects');
      }
    } catch (err) {
      showToast(`Error opening project: ${err.message}`, 'error');
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Initialize Right Panel Inspector Tabs
   */
  initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanels = document.querySelectorAll('.tab-content-panel');

    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');

        // Switch active buttons
        tabButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Switch active panels
        tabPanels.forEach(panel => {
          if (panel.id === `tab-panel-${targetTab}`) {
            panel.classList.add('active');
          } else {
            panel.classList.remove('active');
          }
        });

        // Trigger on-demand tab data loading
        if (targetTab === 'lyrics' && typeof loadLyrics === 'function' && typeof appState !== 'undefined' && appState.projectId) {
          if (!appState.lyricSegments || appState.lyricSegments.length === 0) {
            loadLyrics(appState.projectId);
          }
        }
      });
    });
  }

  /**
   * Sync Inspector controls with appState
   */
  initInspectorBindings() {
    // Face identity slider
    const faceSlider = document.getElementById('slider-face-weight');
    const faceValTag = document.getElementById('val-face-weight');
    if (faceSlider && faceValTag) {
      faceSlider.addEventListener('input', (e) => {
        const val = e.target.value;
        faceValTag.textContent = `${val}%`;
        appState.effects.faceIdentityWeight = parseInt(val, 10);
      });
    }

    // Motion strength slider
    const motionSlider = document.getElementById('slider-motion-strength');
    const motionValTag = document.getElementById('val-motion-strength');
    if (motionSlider && motionValTag) {
      motionSlider.addEventListener('input', (e) => {
        const val = e.target.value;
        motionValTag.textContent = `${val}%`;
        appState.effects.motionStrength = parseInt(val, 10);
      });
    }

    // Style selector cards in Left Panel
    const styleCards = document.querySelectorAll('.style-card');
    styleCards.forEach(card => {
      card.addEventListener('click', () => {
        if (card.classList.contains('disabled')) {
          showToast('Style coming in future AI integration phases', 'info');
          return;
        }

        styleCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        appState.selectedStyle = card.getAttribute('data-style');
        
        // Update Inspector display
        const inspectorStyle = document.getElementById('inspector-selected-style');
        if (inspectorStyle) {
          inspectorStyle.textContent = card.querySelector('.style-name').textContent;
        }
      });
    });

    // Switches in Left Panel & Inspector
    const switchLyrics = document.getElementById('switch-lyrics');
    const switchLyricsInspector = document.getElementById('switch-lyrics-inspector');
    const lyricsOptions = document.getElementById('lyrics-options-container');

    const toggleLyrics = (checked) => {
      appState.effects.kineticLyrics = checked;
      if (switchLyrics) switchLyrics.checked = checked;
      if (switchLyricsInspector) switchLyricsInspector.checked = checked;
      if (lyricsOptions) {
        lyricsOptions.style.display = checked ? 'flex' : 'none';
      }
    };

    if (switchLyrics) {
      switchLyrics.addEventListener('change', (e) => toggleLyrics(e.target.checked));
    }
    if (switchLyricsInspector) {
      switchLyricsInspector.addEventListener('change', (e) => toggleLyrics(e.target.checked));
    }

    const switchBg = document.getElementById('switch-bg');
    const switchBgInspector = document.getElementById('switch-bg-inspector');
    const toggleBg = (checked) => {
      appState.effects.adaptiveBackground = checked;
      if (switchBg) switchBg.checked = checked;
      if (switchBgInspector) switchBgInspector.checked = checked;
    };

    if (switchBg) {
      switchBg.addEventListener('change', (e) => toggleBg(e.target.checked));
    }
    if (switchBgInspector) {
      switchBgInspector.addEventListener('change', (e) => toggleBg(e.target.checked));
    }

    const switchMasking = document.getElementById('switch-masking-inspector');
    if (switchMasking) {
      switchMasking.addEventListener('change', (e) => {
        appState.effects.characterMasking = e.target.checked;
      });
    }

    // Lyrics style & position selectors
    const lyricsStyleSelect = document.getElementById('select-lyrics-style');
    if (lyricsStyleSelect) {
      lyricsStyleSelect.addEventListener('change', (e) => {
        appState.effects.lyricsStyle = e.target.value;
      });
    }

    const lyricsPosSelect = document.getElementById('select-lyrics-pos');
    if (lyricsPosSelect) {
      lyricsPosSelect.addEventListener('change', (e) => {
        appState.effects.lyricsPosition = e.target.value;
      });
    }
  }

  /**
   * Keyboard shortcuts for creative studio productivity
   */
  initKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Ignore if typing in text input
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

      if (e.code === 'Space') {
        e.preventDefault();
        const playBtn = document.getElementById('btn-play-pause');
        if (playBtn) playBtn.click();
      } else if (e.key === 'm' || e.key === 'M') {
        const muteBtn = document.getElementById('btn-mute');
        if (muteBtn) muteBtn.click();
      } else if (e.key === 'f' || e.key === 'F') {
        const fsBtn = document.getElementById('btn-fullscreen');
        if (fsBtn) fsBtn.click();
      } else if (e.key === 'l' || e.key === 'L') {
        const termBtn = document.getElementById('btn-toggle-terminal');
        if (termBtn) termBtn.click();
      } else if (e.key === 't' || e.key === 'T') {
        const kineticDemoBtn = document.getElementById('btn-demo-kinetic');
        if (kineticDemoBtn) kineticDemoBtn.click();
      }
    });
  }
}
