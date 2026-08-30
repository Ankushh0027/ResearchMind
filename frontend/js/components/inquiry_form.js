/**
 * ResearchMind - Inquiry Form Component
 */

export function renderInquiryForm(container, store, onSubmit) {
  let selectedTags = new Set(['physics', 'materials science']);

  const SUGGESTIONS = [
    'Analyze the current state of retrieval-augmented generation for scientific research, identify the major reliability challenges, compare approaches, and provide evidence-backed conclusions.',
    'Room-temperature superconductivity in hydride compounds under high pressure',
    'Quantum topological insulators and Majorana zero modes in solid-state devices',
    'CRISPR-Cas9 off-target mitigation strategies in clinical human therapeutics',
  ];

  const update = (state) => {
    const isRunning = ['QUEUED', 'PLANNING', 'RESEARCHING', 'ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING'].includes(state.runStage);
    const disabledAttr = (state.isSubmitting || isRunning) ? 'disabled' : '';

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>🔬 Launch Autonomous Research Inquiry</span>
          ${state.currentRunId ? `<span class="badge badge-health-ok" style="font-family: var(--font-mono);">${state.currentRunId}</span>` : ''}
        </div>

        <form id="inquiry-form">
          <div class="form-group">
            <label class="form-label" for="inquiry-query">Research Topic / Inquiry Objective</label>
            <textarea
              id="inquiry-query"
              class="form-textarea"
              placeholder="e.g. Investigate recent progress in cuprate high-Tc superconductivity mechanisms..."
              required
              minlength="3"
              maxlength="2000"
              ${disabledAttr}
            >${state.goalQuery || ''}</textarea>
          </div>

          <div style="margin-bottom: 0.75rem;">
            <span class="form-label" style="display: block; margin-bottom: 0.25rem;">Suggested Research Inquiries:</span>
            <div class="tag-chips">
              ${SUGGESTIONS.map((s, idx) => `
                <button type="button" class="tag-chip suggestion-btn" data-query="${s}" ${disabledAttr}>${s.slice(0, 45)}...</button>
              `).join('')}
            </div>
          </div>

          <div class="input-row">
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label" for="inquiry-tags">Domain Focus Tags (comma-separated)</label>
              <input
                id="inquiry-tags"
                type="text"
                class="form-input"
                value="${Array.from(selectedTags).join(', ')}"
                placeholder="physics, condensed matter, superconductivity"
                ${disabledAttr}
              />
            </div>

            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label" for="inquiry-subtasks">Max Decomposed Subtasks (<span id="subtasks-val">10</span>)</label>
              <input
                id="inquiry-subtasks"
                type="range"
                min="1"
                max="30"
                value="10"
                class="form-input"
                style="padding: 0.2rem;"
                ${disabledAttr}
              />
            </div>

            <div>
              <button
                type="submit"
                id="btn-submit-inquiry"
                class="btn btn-primary"
                ${disabledAttr}
              >
                ${state.isSubmitting ? 'Submitting...' : '🚀 Start Investigation'}
              </button>
            </div>
          </div>

          ${state.error ? `
            <div style="margin-top: 1rem; padding: 0.75rem 1rem; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: var(--radius-md); color: var(--status-failed);">
              <strong>Error:</strong> ${state.error}
            </div>
          ` : ''}
        </form>
      </div>
    `;

    const form = container.querySelector('#inquiry-form');
    const queryInput = container.querySelector('#inquiry-query');
    const tagsInput = container.querySelector('#inquiry-tags');
    const subtasksInput = container.querySelector('#inquiry-subtasks');
    const subtasksVal = container.querySelector('#subtasks-val');

    subtasksInput?.addEventListener('input', (e) => {
      if (subtasksVal) subtasksVal.textContent = e.target.value;
    });

    container.querySelectorAll('.suggestion-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (queryInput) {
          queryInput.value = btn.getAttribute('data-query');
          queryInput.focus();
        }
      });
    });

    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const query = (queryInput?.value || '').trim();
      const tags = (tagsInput?.value || '')
        .split(',')
        .map(t => t.trim())
        .filter(Boolean);
      const maxSubtasks = parseInt(subtasksInput?.value || '10', 10);

      if (query.length >= 3) {
        onSubmit({ query, domain_tags: tags, max_subtasks: maxSubtasks });
      }
    });
  };

  store.subscribe(update);
  update(store.getState());
}
