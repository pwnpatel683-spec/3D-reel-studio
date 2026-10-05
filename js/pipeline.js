/**
 * ===================================================================
 * 3D REEL STUDIO — Processing Pipeline & Telemetry Controller
 * Phase 1 Frontend Foundation
 * ===================================================================
 */

class PipelineController {
  constructor(trackContainer, terminalElement, toggleBtn) {
    this.trackContainer = trackContainer;
    this.terminalBody = terminalElement;
    this.toggleBtn = toggleBtn;
    this.dockElement = document.querySelector('.studio-bottom-dock');
    this.isTerminalExpanded = false;

    this.init();
  }

  /**
   * Initialize pipeline nodes and bind terminal controls
   */
  init() {
    this.renderPipelineNodes();
    this.bindTerminalToggle();
    this.logInitialSystemStatus();
  }

  /**
   * Render the 11 processing pipeline nodes into the timeline track
   */
  renderPipelineNodes() {
    if (!this.trackContainer) return;
    this.trackContainer.innerHTML = '';

    const stages = Object.values(appState.processingStatus);

    stages.forEach((stage, index) => {
      const stepEl = document.createElement('div');
      stepEl.className = `pipeline-step status-${stage.status}`;
      stepEl.id = `pipeline-step-${stage.id}`;
      stepEl.setAttribute('data-stage-id', stage.id);
      stepEl.title = `${stage.name}: ${stage.description}`;

      stepEl.innerHTML = `
        <div class="step-num-badge">${String(stage.id).padStart(2, '0')}</div>
        <div class="step-info">
          <span class="step-name">${stage.name}</span>
          <span class="step-status-tag" id="step-tag-${stage.id}">
            ${this.getStatusIcon(stage.status)} ${stage.status}
          </span>
        </div>
      `;

      this.trackContainer.appendChild(stepEl);

      // Add connecting chevron between nodes except for last item
      if (index < stages.length - 1) {
        const connector = document.createElement('div');
        connector.className = 'pipeline-connector';
        connector.innerHTML = '›';
        this.trackContainer.appendChild(connector);
      }
    });
  }

  /**
   * Get micro icon for each status state
   */
  getStatusIcon(status) {
    switch (status) {
      case 'ready': return '●';
      case 'processing': return '◐';
      case 'completed': return '✓';
      case 'failed': return '✕';
      default: return '○';
    }
  }

  /**
   * Update the status and visual state of a specific pipeline stage
   * @param {number} stageId - 1 to 11
   * @param {'ready'|'pending'|'processing'|'completed'|'failed'} status 
   * @param {string} [detail] - Optional log or detail text
   */
  updatePipelineStage(stageId, status, detail = null) {
    if (!appState.processingStatus[stageId]) return;

    appState.processingStatus[stageId].status = status;
    const stepEl = document.getElementById(`pipeline-step-${stageId}`);
    const tagEl = document.getElementById(`step-tag-${stageId}`);

    if (stepEl && tagEl) {
      stepEl.className = `pipeline-step status-${status}`;
      tagEl.innerHTML = `${this.getStatusIcon(status)} ${status}`;
    }

    if (detail) {
      this.updateStatus(`[Stage ${stageId}: ${appState.processingStatus[stageId].name}] ${detail}`, 
        status === 'failed' ? 'error' : status === 'completed' ? 'success' : 'info'
      );
    }
  }

  /**
   * Bind collapsible terminal controls
   */
  bindTerminalToggle() {
    if (!this.toggleBtn || !this.dockElement) return;

    this.toggleBtn.addEventListener('click', () => {
      this.isTerminalExpanded = !this.isTerminalExpanded;
      this.dockElement.classList.toggle('terminal-expanded', this.isTerminalExpanded);
      this.toggleBtn.classList.toggle('active', this.isTerminalExpanded);
      this.toggleBtn.innerHTML = this.isTerminalExpanded 
        ? '<span>✕ Close Terminal</span>' 
        : '<span>◈ Telemetry Log</span>';
    });

    // Clear Terminal button
    const clearBtn = document.getElementById('btn-clear-terminal');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (this.terminalBody) {
          this.terminalBody.innerHTML = '';
          this.updateStatus('Terminal buffer cleared.', 'info');
        }
      });
    }

    // Copy Logs button
    const copyBtn = document.getElementById('btn-copy-terminal');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const text = appState.logs.map(l => `[${l.time}] [${l.type.toUpperCase()}] ${l.message}`).join('\n');
        navigator.clipboard.writeText(text).then(() => {
          showToast('Telemetry logs copied to clipboard', 'info');
        });
      });
    }
  }

  /**
   * Appends a new timestamped log message to the terminal drawer and state
   * @param {string} message - Text message
   * @param {'info'|'success'|'warning'|'error'} type 
   */
  updateStatus(message, type = 'info') {
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');

    // Store in global app state
    appState.logs.push({ time: timeStr, message, type });

    if (!this.terminalBody) return;

    const line = document.createElement('div');
    line.className = 'terminal-line';
    line.innerHTML = `
      <span class="terminal-time">${timeStr}</span>
      <span class="terminal-badge ${type}">${type}</span>
      <span class="terminal-msg">${this.escapeHtml(message)}</span>
    `;

    this.terminalBody.appendChild(line);
    this.terminalBody.scrollTop = this.terminalBody.scrollHeight;
  }

  /**
   * Initial terminal message
   */
  logInitialSystemStatus() {
    this.updateStatus('System ready.', 'info');
    this.updateStatus(`Project Session Initialized: ${appState.projectId}`, 'info');
    this.updateStatus('Awaiting source video input...', 'info');
  }

  escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}
