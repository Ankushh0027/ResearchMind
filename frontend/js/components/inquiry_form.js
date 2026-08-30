/**
 * ResearchMind - Clean Research Inquiry Input (Screen 1)
 */

export function renderInquiryForm(container, store, onSubmit) {
  let selectedTags = new Set(['ai', 'developer tools', 'productivity']);

  const SUGGESTIONS = [
    {
      label: '⚡ Impact of AI Coding Assistants',
      query: 'What is the impact of AI coding assistants on software developer productivity, code quality, and defect rates?',
      tags: ['ai', 'developer tools', 'productivity'],
    },
    {
      label: '🔬 RAG for Scientific Research',
      query: 'Analyze the current state of retrieval-augmented generation for scientific research, identify the major reliability challenges, compare approaches, and provide evidence-backed conclusions.',
      tags: ['ai', 'rag', 'scientific research', 'reliability'],
    },
    {
      label: '⚛️ Room-Temperature Superconductivity',
      query: 'Investigate recent empirical claims and replication attempts regarding room-temperature superconductivity in high-pressure hydride compounds.',
      tags: ['physics', 'materials science', 'superconductivity'],
    },
    {
      label: '🧬 CRISPR-Cas9 Off-Target Mitigation',
      query: 'Compare high-fidelity Cas9 variants, prime editing, and base editing strategies for minimizing off-target genomic cleavage in clinical gene therapy.',
      tags: ['biomedical', 'genetics', 'crispr', 'therapeutics'],
    },
  ];

  const escapeHtml = (unsafe) => {
    return (unsafe || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const update = (state) => {
    const isSubmitting = state.isSubmitting;

    container.innerHTML = `
      <div class="inquiry-hero">
        <div class="hero-badge">Autonomous Multi-Agent Investigation</div>
        <h2 class="hero-title">What do you want to investigate?</h2>
        <p class="hero-subtitle">
          ResearchMind decomposes open-ended questions into parallel agent DAGs, retrieves empirical evidence across arXiv & the web, detects factual contradictions, and compiles verifiable research dossiers.
        </p>

        <form id="inquiry-form" class="inquiry-card">
          <div class="form-group">
            <textarea
              id="inquiry-query"
              class="form-textarea hero-textarea"
              placeholder="e.g. What is the impact of AI coding assistants on software developer productivity?"
              required
              minlength="3"
              maxlength="2000"
              ${isSubmitting ? 'disabled' : ''}
            >${escapeHtml(state.goalQuery || '')}</textarea>
          </div>

          <div class="suggestions-section">
            <span class="suggestion-label">Suggested Research Questions:</span>
            <div class="tag-chips">
              ${SUGGESTIONS.map((s, idx) => `
                <button
                  type="button"
                  class="tag-chip suggestion-btn"
                  data-index="${idx}"
                  ${isSubmitting ? 'disabled' : ''}
                >
                  ${escapeHtml(s.label)}
                </button>
              `).join('')}
            </div>
          </div>

          <div class="inquiry-controls">
            <div class="form-group" style="flex: 2; margin-bottom: 0;">
              <label class="form-label" for="inquiry-tags">Domain Focus Tags</label>
              <input
                id="inquiry-tags"
                type="text"
                class="form-input"
                value="${escapeHtml(Array.from(selectedTags).join(', '))}"
                placeholder="ai, software engineering, productivity"
                ${isSubmitting ? 'disabled' : ''}
              />
            </div>

            <div class="form-group" style="flex: 1; margin-bottom: 0;">
              <label class="form-label" for="inquiry-subtasks">Max Subtasks (<span id="subtasks-val">10</span>)</label>
              <input
                id="inquiry-subtasks"
                type="range"
                min="2"
                max="25"
                value="10"
                class="form-range"
                ${isSubmitting ? 'disabled' : ''}
              />
            </div>

            <div style="display: flex; align-items: flex-end;">
              <button
                type="submit"
                id="btn-submit-inquiry"
                class="btn btn-primary btn-large"
                ${isSubmitting ? 'disabled' : ''}
              >
                ${isSubmitting ? 'Initiating Pipeline...' : '🚀 Start Investigation'}
              </button>
            </div>
          </div>

          ${state.error ? `
            <div class="error-banner">
              <strong>Error:</strong> ${escapeHtml(state.error)}
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
        const idx = parseInt(btn.getAttribute('data-index') || '0', 10);
        const item = SUGGESTIONS[idx];
        if (item && queryInput) {
          queryInput.value = item.query;
          if (tagsInput) tagsInput.value = item.tags.join(', ');
          selectedTags = new Set(item.tags);
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
