/**
 * ResearchMind - Multi-Agent Pipeline DAG Component
 */

export function renderAgentDag(container, store, onCancel) {
  const AGENTS = [
    { role: 'PLANNER', label: 'Planner', desc: 'DAG Decomposition' },
    { role: 'RESEARCHER', label: 'Researcher', desc: 'Academic & Web Ingestion' },
    { role: 'ANALYST', label: 'Analyst', desc: 'Claim Extraction & Synthesis' },
    { role: 'VERIFIER', label: 'Verifier', desc: 'Contradiction & Grounding' },
    { role: 'EVALUATOR', label: 'Evaluator', desc: 'Quality Audit & Refinement' },
    { role: 'REPORTER', label: 'Reporter', desc: 'Dossier Compilation' },
  ];

  const update = (state) => {
    const isRunning = ['QUEUED', 'PLANNING', 'RESEARCHING', 'ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING'].includes(state.runStage);

    let stageBadge = 'badge-health-ok';
    if (state.runStage === 'FAILED') stageBadge = 'badge-health-err';
    if (state.runStage === 'CANCELLED') stageBadge = 'badge';

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span>⚡ Multi-Agent Execution Pipeline</span>
            <span class="badge ${stageBadge}">
              ${isRunning ? '<span class="status-dot pulse"></span>' : ''}
              Stage: ${state.runStage}
            </span>
          </div>

          <div>
            ${isRunning ? `
              <button id="btn-cancel-run" class="btn btn-danger btn-sm">
                ⏹ Cancel Run
              </button>
            ` : ''}
          </div>
        </div>

        <div class="pipeline-container">
          <div class="agent-steps">
            ${AGENTS.map(agent => {
              const status = state.agentStages[agent.role] || 'idle';
              let icon = '⚪';
              let extraClass = '';

              if (status === 'running') {
                icon = '🔵';
                extraClass = 'active';
              } else if (status === 'completed') {
                icon = '🟢';
                extraClass = 'completed';
              } else if (status === 'failed') {
                icon = '🔴';
                extraClass = 'failed';
              } else if (status === 'queued') {
                icon = '🟡';
              }

              return `
                <div class="agent-card ${extraClass}">
                  <span style="font-size: 1.25rem;">${icon}</span>
                  <span class="agent-role">${agent.label}</span>
                  <span class="agent-status-label">${agent.desc}</span>
                  <span style="font-size: 0.65rem; text-transform: uppercase; font-weight: 700; color: var(--text-muted); margin-top: 0.2rem;">${status}</span>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      </div>
    `;

    container.querySelector('#btn-cancel-run')?.addEventListener('click', onCancel);
  };

  store.subscribe(update);
  update(store.getState());
}
