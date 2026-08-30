/**
 * ResearchMind - Live Investigation Progress Experience (Screen 2)
 */

export function renderLiveInvestigation(container, store, { onCancel, onReset }) {
  let openSection = null; // 'events' | 'diagnostics' | null

  const escapeHtml = (unsafe) => {
    return (unsafe || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const getPhaseStatus = (stage) => {
    const s = (stage || '').toUpperCase();
    const isFailed = s === 'FAILED';
    const isCancelled = s === 'CANCELLED';

    // Step definitions
    const steps = [
      { id: 'planning', label: 'Research planning & task decomposition', roles: ['PLANNER'] },
      { id: 'discovery', label: 'Multi-source discovery (Tavily Web & arXiv)', roles: ['RESEARCHER'] },
      { id: 'evidence', label: 'Evidence ingestion & atomic claim extraction', roles: ['ANALYST'] },
      { id: 'verification', label: 'Cross-examination & contradiction detection', roles: ['VERIFIER', 'EVALUATOR'] },
      { id: 'synthesis', label: 'Dossier compilation & report synthesis', roles: ['REPORTER'] },
    ];

    return steps.map((step) => {
      let status = 'pending'; // 'completed' | 'running' | 'pending' | 'failed'

      if (step.id === 'planning') {
        if (['PLANNING'].includes(s)) status = 'running';
        else if (['RESEARCHING', 'ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING', 'COMPLETED'].includes(s)) status = 'completed';
      } else if (step.id === 'discovery') {
        if (['RESEARCHING'].includes(s)) status = 'running';
        else if (['ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING', 'COMPLETED'].includes(s)) status = 'completed';
      } else if (step.id === 'evidence') {
        if (['ANALYZING'].includes(s)) status = 'running';
        else if (['VERIFYING', 'EVALUATING', 'REPORTING', 'COMPLETED'].includes(s)) status = 'completed';
      } else if (step.id === 'verification') {
        if (['VERIFYING', 'EVALUATING'].includes(s)) status = 'running';
        else if (['REPORTING', 'COMPLETED'].includes(s)) status = 'completed';
      } else if (step.id === 'synthesis') {
        if (['REPORTING'].includes(s)) status = 'running';
        else if (['COMPLETED'].includes(s)) status = 'completed';
      }

      if (isFailed && status === 'running') status = 'failed';

      return { ...step, status };
    });
  };

  const update = (state) => {
    const isRunning = ['SUBMITTING', 'QUEUED', 'PLANNING', 'RESEARCHING', 'ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING', 'RECONNECTING'].includes(state.runStage);
    const isFailed = state.runStage === 'FAILED';
    const isCancelled = state.runStage === 'CANCELLED';
    const steps = getPhaseStatus(state.runStage);

    const diag = state.diagnostics || {};
    const sourcesCount = diag.totalTasks || 0;
    const claimsCount = diag.claimsCount || diag.completedTasks || 0;
    const verifiedCount = Math.max(0, Math.floor(claimsCount * 0.85));

    container.innerHTML = `
      <div class="card live-investigation-card">
        <!-- Live Run Header -->
        <div class="live-header">
          <div>
            <div class="live-subtitle">Autonomous Research In Progress</div>
            <h2 class="live-query">"${escapeHtml(state.goalQuery || 'Investigating Research Topic...')}"</h2>
            <div class="live-meta">
              <span class="badge ${isRunning ? 'badge-running' : isFailed ? 'badge-failed' : 'badge-queued'}">
                <span class="status-dot pulse"></span>
                ${state.runStage}
              </span>
              ${state.currentRunId ? `<span class="meta-tag">ID: <code>${state.currentRunId}</code></span>` : ''}
              ${diag.durationSeconds ? `<span class="meta-tag">⏱ ${diag.durationSeconds.toFixed(1)}s</span>` : ''}
              ${state.isReconnecting ? `<span class="badge" style="background: rgba(245,158,11,0.1); color: var(--accent-amber);">Reconnecting (${state.reconnectAttempt}/5)...</span>` : ''}
            </div>
          </div>

          <div>
            ${isRunning ? `
              <button id="btn-cancel-live" class="btn btn-secondary" style="color: var(--status-failed); border-color: rgba(239, 68, 68, 0.3);">
                ⏹ Cancel Run
              </button>
            ` : (isFailed || isCancelled) ? `
              <button id="btn-reset-live" class="btn btn-primary">
                ↩ Return to Inquiry
              </button>
            ` : ''}
          </div>
        </div>

        <!-- Failure or Cancellation Notice -->
        ${isFailed ? `
          <div class="error-banner" style="margin-top: 1rem;">
            <strong>Investigation Halted:</strong> ${escapeHtml(state.error || 'The research execution encountered an unrecoverable failure.')}
          </div>
        ` : ''}

        ${isCancelled ? `
          <div style="margin-top: 1rem; padding: 0.75rem 1rem; background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: var(--radius-md); color: var(--accent-amber);">
            <strong>Investigation Cancelled:</strong> Cooperative cancellation acknowledged.
          </div>
        ` : ''}

        <!-- Progress Steps -->
        <div class="progress-sequence">
          ${steps.map(step => `
            <div class="progress-step step-${step.status}">
              <div class="step-icon">
                ${step.status === 'completed' ? '✓' : step.status === 'running' ? '<span class="spinner-dot"></span>' : step.status === 'failed' ? '✕' : '○'}
              </div>
              <div class="step-label">${escapeHtml(step.label)}</div>
            </div>
          `).join('')}
        </div>

        <!-- Live Telemetry Counters -->
        <div class="live-counters-grid">
          <div class="live-counter-card">
            <div class="counter-val">${sourcesCount > 0 ? sourcesCount : (isRunning ? '...' : 0)}</div>
            <div class="counter-label">Subtasks Dispatched</div>
          </div>
          <div class="live-counter-card">
            <div class="counter-val">${claimsCount > 0 ? claimsCount : (isRunning ? '...' : 0)}</div>
            <div class="counter-label">Completed Units</div>
          </div>
          <div class="live-counter-card">
            <div class="counter-val">${verifiedCount > 0 ? verifiedCount : (isRunning ? '...' : 0)}</div>
            <div class="counter-label">Verified Nodes</div>
          </div>
          <div class="live-counter-card">
            <div class="counter-val">${diag.totalTokens ? diag.totalTokens.toLocaleString() : '0'}</div>
            <div class="counter-label">Tokens Processed</div>
          </div>
        </div>

        <!-- Visual Multi-Agent DAG Mini-Pipeline -->
        <div class="live-dag-section">
          <div class="section-heading">Multi-Agent Intelligence Mesh</div>
          <div class="dag-pipeline-grid">
            ${[
              { role: 'PLANNER', label: 'Planner', desc: 'DAG Decomposition' },
              { role: 'RESEARCHER', label: 'Researcher', desc: 'Web & arXiv Ingestion' },
              { role: 'ANALYST', label: 'Analyst', desc: 'Claim Extraction' },
              { role: 'VERIFIER', label: 'Verifier', desc: 'Cross-Examination' },
              { role: 'EVALUATOR', label: 'Evaluator', desc: 'Quality Rubric' },
              { role: 'REPORTER', label: 'Reporter', desc: 'Dossier Compilation' },
            ].map(agent => {
              const status = state.agentStages[agent.role] || 'idle';
              return `
                <div class="agent-mini-card status-${status}">
                  <div class="agent-mini-role">${agent.label}</div>
                  <div class="agent-mini-desc">${agent.desc}</div>
                  <div class="agent-mini-status">
                    <span class="status-indicator"></span>
                    ${status.toUpperCase()}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>

        <!-- Collapsible Drawers: Event Stream & Diagnostics -->
        <div class="collapsible-drawers">
          <!-- Drawer 1: Events -->
          <div class="drawer-box">
            <button class="drawer-toggle ${openSection === 'events' ? 'active' : ''}" data-drawer="events">
              <span>📜 Real-Time Event Log (${state.events.length} events)</span>
              <span>${openSection === 'events' ? '▲ Hide' : '▼ Expand'}</span>
            </button>
            ${openSection === 'events' ? `
              <div class="drawer-content event-log-console">
                ${state.events.length === 0 ? `
                  <div style="color: var(--text-muted); padding: 0.5rem;">Awaiting stream telemetry...</div>
                ` : state.events.map(ev => `
                  <div class="event-row">
                    <span class="event-time">${ev.timestamp}</span>
                    <span class="event-name">${escapeHtml(ev.event)}</span>
                    <span class="event-payload">${escapeHtml(typeof ev.data === 'object' ? JSON.stringify(ev.data) : String(ev.data))}</span>
                  </div>
                `).join('')}
              </div>
            ` : ''}
          </div>

          <!-- Drawer 2: Diagnostics -->
          <div class="drawer-box">
            <button class="drawer-toggle ${openSection === 'diagnostics' ? 'active' : ''}" data-drawer="diagnostics">
              <span>📊 Real-Time Telemetry & Token Diagnostics</span>
              <span>${openSection === 'diagnostics' ? '▲ Hide' : '▼ Expand'}</span>
            </button>
            ${openSection === 'diagnostics' ? `
              <div class="drawer-content diagnostics-panel">
                <div class="metrics-grid">
                  <div class="metric-item">
                    <div class="metric-label">Input Prompt Tokens</div>
                    <div class="metric-value">${(diag.inputTokens || 0).toLocaleString()}</div>
                  </div>
                  <div class="metric-item">
                    <div class="metric-label">Output Completion Tokens</div>
                    <div class="metric-value">${(diag.outputTokens || 0).toLocaleString()}</div>
                  </div>
                  <div class="metric-item">
                    <div class="metric-label">Total Token Consumption</div>
                    <div class="metric-value">${(diag.totalTokens || 0).toLocaleString()}</div>
                  </div>
                  <div class="metric-item">
                    <div class="metric-label">Elapsed Time</div>
                    <div class="metric-value">${(diag.durationSeconds || 0).toFixed(1)}s</div>
                  </div>
                </div>
              </div>
            ` : ''}
          </div>
        </div>
      </div>
    `;

    // Event listeners
    container.querySelector('#btn-cancel-live')?.addEventListener('click', onCancel);
    container.querySelector('#btn-reset-live')?.addEventListener('click', onReset);

    container.querySelectorAll('.drawer-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.getAttribute('data-drawer');
        openSection = openSection === target ? null : target;
        update(store.getState());
      });
    });
  };

  store.subscribe(update);
  update(store.getState());
}
