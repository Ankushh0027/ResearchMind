/**
 * ResearchMind - Run Diagnostics & Quality Metrics Component
 */

export function renderDiagnostics(container, store) {
  const update = (state) => {
    const diag = state.diagnostics;
    const dossier = state.dossier;

    const claimsCount = dossier?.claims?.length ?? diag.claimsCount ?? 0;
    const contradictionsCount = dossier?.contradictions?.length ?? diag.contradictionsCount ?? 0;
    const scoreVal = dossier?.evaluation?.overall_score ?? dossier?.confidence_rating ?? diag.overallScore;
    const formattedScore = scoreVal !== null && scoreVal !== undefined ? `${(scoreVal * 100).toFixed(1)}%` : 'Pending';

    container.innerHTML = `
      <div class="card" style="height: 100%;">
        <div class="card-title">
          <span>📊 Run Diagnostics & Quality Telemetry</span>
        </div>

        <div class="metrics-grid">
          <div class="metric-item">
            <span class="metric-label">Quality Score</span>
            <span class="metric-val" style="color: ${scoreVal && scoreVal >= 0.85 ? 'var(--accent-emerald)' : 'var(--text-primary)'};">
              ${formattedScore}
            </span>
          </div>

          <div class="metric-item">
            <span class="metric-label">Extracted Claims</span>
            <span class="metric-val" style="color: var(--accent-cyan);">
              ${claimsCount}
            </span>
          </div>

          <div class="metric-item">
            <span class="metric-label">Contradictions</span>
            <span class="metric-val" style="color: ${contradictionsCount > 0 ? 'var(--accent-amber)' : 'var(--accent-emerald)'};">
              ${contradictionsCount}
            </span>
          </div>

          <div class="metric-item">
            <span class="metric-label">Token Consumption</span>
            <span class="metric-val" style="font-size: 1rem;">
              ${diag.totalTokens.toLocaleString()}
            </span>
            <span style="font-size: 0.65rem; color: var(--text-muted);">
              IN: ${diag.inputTokens.toLocaleString()} | OUT: ${diag.outputTokens.toLocaleString()}
            </span>
          </div>

          <div class="metric-item">
            <span class="metric-label">Tasks Completed</span>
            <span class="metric-val">
              ${diag.completedTasks} ${diag.totalTasks > 0 ? `/ ${diag.totalTasks}` : ''}
            </span>
          </div>

          <div class="metric-item">
            <span class="metric-label">Execution Duration</span>
            <span class="metric-val">
              ${diag.durationSeconds ? `${diag.durationSeconds.toFixed(1)}s` : '0.0s'}
            </span>
          </div>
        </div>
      </div>
    `;
  };

  store.subscribe(update);
  update(store.getState());
}
