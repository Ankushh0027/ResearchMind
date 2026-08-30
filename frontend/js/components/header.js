/**
 * ResearchMind - Header & System Status Component
 */

export function renderHeader(container, store, onOpenSettings) {
  const update = (state) => {
    const isOk = state.health.status === 'ok';
    const healthClass = isOk ? 'badge-health-ok' : 'badge-health-err';
    const statusText = isOk ? 'API Online' : 'API Connecting...';
    const maskedKey = store.getMaskedApiKey();

    container.innerHTML = `
      <div class="brand-section">
        <div class="brand-logo">RM</div>
        <div>
          <h1 class="brand-title">ResearchMind</h1>
          <span class="brand-tag">Autonomous Multi-Agent Investigation Studio</span>
        </div>
      </div>

      <div class="header-actions">
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
  };

  store.subscribe(update);
  update(store.getState());
}
