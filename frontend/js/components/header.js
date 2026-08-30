/**
 * ResearchMind - Header & System Status Component
 */

export function renderHeader(container, store, { onOpenSettings, onNewInvestigation }) {
  const update = (state) => {
    const isOk = state.health.status === 'ok';
    const healthClass = isOk ? 'badge-health-ok' : 'badge-health-err';
    const statusText = isOk ? 'API Online' : 'Connecting...';
    const maskedKey = store.getMaskedApiKey();
    const isCompleted = state.runStage === 'COMPLETED';

    container.innerHTML = `
      <div class="brand-section">
        <div class="brand-logo">RM</div>
        <div>
          <h1 class="brand-title">ResearchMind</h1>
          <span class="brand-tag">Evidence-Backed Autonomous Research</span>
        </div>
      </div>

      <div class="header-actions">
        ${isCompleted ? `
          <button id="btn-header-new" class="btn btn-secondary btn-sm" style="border-color: var(--accent-primary); color: var(--text-primary);">
            + New Investigation
          </button>
        ` : ''}

        <span class="badge ${healthClass}">
          <span class="status-dot ${isOk ? '' : 'pulse'}"></span>
          ${statusText}
        </span>
        
        <button id="btn-open-settings" class="btn btn-secondary btn-sm" title="Configure API Credentials">
          🔑 Key: <code>${maskedKey}</code>
        </button>
      </div>
    `;

    container.querySelector('#btn-open-settings')?.addEventListener('click', onOpenSettings);
    container.querySelector('#btn-header-new')?.addEventListener('click', onNewInvestigation);
  };

  store.subscribe(update);
  update(store.getState());
}
