/**
 * ResearchMind - Durable Artifact & Evidence Explorer Component
 */

export function renderArtifactExplorer(container, store, onDownload) {
  const update = (state) => {
    const artifacts = state.artifacts || [];

    if (artifacts.length === 0) {
      container.innerHTML = `
        <div class="card">
          <div class="card-title">
            <span>📦 Persistent Artifacts & Checkpoints</span>
          </div>
          <div style="color: var(--text-muted); text-align: center; padding: 2rem 1rem;">
            No persistent artifacts recorded for this inquiry session.
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>📦 Persistent Artifacts & Checkpoints (${artifacts.length})</span>
        </div>

        <div style="display: flex; flex-direction: column; gap: 0.75rem;">
          ${artifacts.map(art => {
            const fileName = art.object_key.split('/').pop() || art.artifact_id;
            const sizeKb = (art.size_bytes / 1024).toFixed(1);

            return `
              <div class="finding-card" style="margin-bottom: 0;">
                <div class="finding-header">
                  <div>
                    <span style="font-weight: 700; color: var(--text-primary);">${escapeHtml(fileName)}</span>
                    <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.5rem;">${art.content_type} (${sizeKb} KB)</span>
                  </div>

                  <button class="btn btn-secondary btn-sm btn-download-art" data-art-id="${art.artifact_id}">
                    ⬇ Download
                  </button>
                </div>

                <div class="meta-row">
                  <span>SHA-256 ETag: <code style="color: var(--accent-emerald);">${art.sha256.slice(0, 16)}...</code></span>
                  <span>Object Key: <code>${escapeHtml(art.object_key)}</code></span>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    container.querySelectorAll('.btn-download-art').forEach(btn => {
      btn.addEventListener('click', () => {
        const artId = btn.getAttribute('data-art-id');
        if (artId) onDownload(artId);
      });
    });
  };

  function escapeHtml(str) {
    return (str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  store.subscribe(update);
  update(store.getState());
}
