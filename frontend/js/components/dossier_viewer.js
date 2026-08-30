/**
 * ResearchMind - Interactive Research Dossier Viewer Component
 */

export function renderDossierViewer(container, store) {
  let activeTab = 'summary';

  const update = (state) => {
    const dossier = state.dossier;

    if (!dossier) {
      container.innerHTML = `
        <div class="card">
          <div class="card-title">
            <span>📑 Final Research Dossier</span>
          </div>
          <div style="text-align: center; padding: 3rem 1rem; color: var(--text-muted);">
            <span style="font-size: 2rem; display: block; margin-bottom: 0.5rem;">📄</span>
            No compiled ResearchDossier available yet. Submit a research inquiry to generate deliverables.
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span>📑 Research Dossier: ${escapeHtml(dossier.goal_query.slice(0, 50))}...</span>
            <span class="badge badge-health-ok">Verified Dossier</span>
          </div>

          <div style="display: flex; gap: 0.5rem;">
            <button id="btn-copy-md" class="btn btn-secondary btn-sm" title="Copy Markdown to clipboard">
              📋 Copy Markdown
            </button>
            <button id="btn-export-md" class="btn btn-secondary btn-sm" title="Export Markdown Report">
              💾 Export .md
            </button>
            <button id="btn-export-json" class="btn btn-secondary btn-sm" title="Export Raw JSON Dossier">
              📦 Export .json
            </button>
          </div>
        </div>

        <div class="tab-header">
          <button class="tab-btn ${activeTab === 'summary' ? 'active' : ''}" data-tab="summary">
            Executive Summary
          </button>
          <button class="tab-btn ${activeTab === 'findings' ? 'active' : ''}" data-tab="findings">
            Key Findings (${dossier.key_findings?.length || 0})
          </button>
          <button class="tab-btn ${activeTab === 'claims' ? 'active' : ''}" data-tab="claims">
            Verified Claims (${dossier.claims?.length || 0})
          </button>
          <button class="tab-btn ${activeTab === 'contradictions' ? 'active' : ''}" data-tab="contradictions">
            Contradictions (${dossier.contradictions?.length || 0})
          </button>
          <button class="tab-btn ${activeTab === 'evaluation' ? 'active' : ''}" data-tab="evaluation">
            Evaluation Report
          </button>
          <button class="tab-btn ${activeTab === 'citations' ? 'active' : ''}" data-tab="citations">
            Evidence Sources (${dossier.citations?.length || 0})
          </button>
        </div>

        <!-- Tab 1: Summary -->
        <div class="tab-pane ${activeTab === 'summary' ? 'active' : ''}" id="pane-summary">
          <div class="prose-section">
            <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem; color: var(--accent-cyan);">Executive Summary</h3>
            <p style="margin-bottom: 1.25rem; white-space: pre-wrap;">${escapeHtml(dossier.executive_summary || 'No executive summary provided.')}</p>

            <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem; color: var(--accent-cyan);">Methodology & Search Strategy</h3>
            <p style="margin-bottom: 1.25rem; white-space: pre-wrap;">${escapeHtml(dossier.methodology_summary || 'No methodology summary recorded.')}</p>

            ${dossier.limitations && dossier.limitations.length > 0 ? `
              <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem; color: var(--accent-amber);">Acknowledged Limitations & Data Gaps</h3>
              <ul style="padding-left: 1.5rem; color: var(--text-secondary);">
                ${dossier.limitations.map(lim => `<li>${escapeHtml(lim)}</li>`).join('')}
              </ul>
            ` : ''}
          </div>
        </div>

        <!-- Tab 2: Findings -->
        <div class="tab-pane ${activeTab === 'findings' ? 'active' : ''}" id="pane-findings">
          ${(!dossier.key_findings || dossier.key_findings.length === 0) ? `
            <div style="color: var(--text-muted); padding: 1rem;">No synthesized findings recorded.</div>
          ` : dossier.key_findings.map(f => `
            <div class="finding-card">
              <div class="finding-header">
                <span class="finding-title">${escapeHtml(f.title)}</span>
                <span class="badge badge-health-ok">Confidence: ${(f.confidence_score * 100).toFixed(0)}%</span>
              </div>
              <p style="color: var(--text-secondary); line-height: 1.5;">${escapeHtml(f.narrative)}</p>
              <div class="meta-row">
                <span>Supporting Claims: <code>${f.claim_ids?.length || 0}</code></span>
                <span>Direct Evidence IDs: <code>${f.evidence_ids?.length || 0}</code></span>
              </div>
            </div>
          `).join('')}
        </div>

        <!-- Tab 3: Claims -->
        <div class="tab-pane ${activeTab === 'claims' ? 'active' : ''}" id="pane-claims">
          ${(!dossier.claims || dossier.claims.length === 0) ? `
            <div style="color: var(--text-muted); padding: 1rem;">No extracted claims recorded.</div>
          ` : dossier.claims.map(c => `
            <div class="claim-card">
              <div class="claim-header">
                <span style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--accent-cyan);">${c.claim_id}</span>
                <span class="badge badge-health-ok">Confidence: ${(c.confidence_score * 100).toFixed(0)}%</span>
              </div>
              <p style="font-weight: 500;">"${escapeHtml(c.statement)}"</p>
              <div class="meta-row">
                ${c.metadata?.source_domain ? `<span>Domain: <strong>${escapeHtml(c.metadata.source_domain)}</strong></span>` : ''}
                ${c.metadata?.source_url ? `<a href="${escapeHtml(c.metadata.source_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary);">Source Link ↗</a>` : ''}
              </div>
            </div>
          `).join('')}
        </div>

        <!-- Tab 4: Contradictions -->
        <div class="tab-pane ${activeTab === 'contradictions' ? 'active' : ''}" id="pane-contradictions">
          ${(!dossier.contradictions || dossier.contradictions.length === 0) ? `
            <div style="color: var(--accent-emerald); padding: 1.5rem; text-align: center; background: rgba(16, 185, 129, 0.05); border-radius: var(--radius-md);">
              ✓ Zero unresolved factual contradictions identified across verified sources.
            </div>
          ` : dossier.contradictions.map(contra => `
            <div class="contra-card" style="border-left: 3px solid var(--accent-amber);">
              <div class="contra-header">
                <span style="font-weight: 700; color: var(--accent-amber);">${escapeHtml(contra.description)}</span>
                <span class="badge" style="background: rgba(245, 158, 11, 0.1); color: var(--accent-amber);">Severity: ${(contra.severity_score * 100).toFixed(0)}%</span>
              </div>
              <p style="color: var(--text-secondary);">${escapeHtml(contra.divergence_analysis)}</p>
              <div class="meta-row">
                <span>Conflicting Claims: <code>${contra.conflicting_claim_ids?.join(', ') || 'N/A'}</code></span>
              </div>
            </div>
          `).join('')}
        </div>

        <!-- Tab 5: Evaluation -->
        <div class="tab-pane ${activeTab === 'evaluation' ? 'active' : ''}" id="pane-evaluation">
          ${!dossier.evaluation ? `
            <div style="color: var(--text-muted); padding: 1rem;">No evaluation audit report attached.</div>
          ` : `
            <div class="metrics-grid" style="margin-bottom: 1.5rem;">
              <div class="metric-item">
                <span class="metric-label">Overall Evaluation Score</span>
                <span class="metric-val" style="color: var(--accent-emerald);">${(dossier.evaluation.overall_score * 100).toFixed(1)}%</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Inquiry Completeness</span>
                <span class="metric-val">${(dossier.evaluation.completeness_score * 100).toFixed(1)}%</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Citation Coverage</span>
                <span class="metric-val">${(dossier.evaluation.citation_coverage_score * 100).toFixed(1)}%</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Unsupported Claim Rate</span>
                <span class="metric-val" style="color: ${(dossier.evaluation.unsupported_claim_rate || 0) > 0.05 ? 'var(--status-failed)' : 'var(--accent-emerald)'};">
                  ${((dossier.evaluation.unsupported_claim_rate || 0) * 100).toFixed(1)}%
                </span>
              </div>
            </div>

            <div class="prose-section">
              <h4 style="font-size: 1rem; color: var(--text-primary); margin-bottom: 0.5rem;">Evaluator Critique</h4>
              <p style="white-space: pre-wrap; color: var(--text-secondary);">${escapeHtml(dossier.evaluation.summary_critique || 'Evaluation criteria satisfied.')}</p>
            </div>
          `}
        </div>

        <!-- Tab 6: Citations -->
        <div class="tab-pane ${activeTab === 'citations' ? 'active' : ''}" id="pane-citations">
          ${(!dossier.citations || dossier.citations.length === 0) ? `
            <div style="color: var(--text-muted); padding: 1rem;">No citations indexed.</div>
          ` : dossier.citations.map(cit => `
            <div class="finding-card">
              <div class="finding-header">
                <span style="font-weight: 700; color: var(--text-primary);">
                  <code style="color: var(--accent-cyan);">${cit.citation_key}</code> ${escapeHtml(cit.title)}
                </span>
                <span class="badge badge-health-ok">${cit.trust_level}</span>
              </div>
              <div class="meta-row">
                <span>Domain: <strong>${escapeHtml(cit.domain)}</strong></span>
                ${cit.publication_date ? `<span>Published: ${cit.publication_date}</span>` : ''}
                ${cit.source_url ? `<a href="${escapeHtml(cit.source_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--accent-primary);">View Source Document ↗</a>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    // Wire tab switches
    container.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.getAttribute('data-tab');
        update(store.getState());
      });
    });

    // Wire export handlers
    container.querySelector('#btn-copy-md')?.addEventListener('click', () => {
      if (dossier.markdown_report) {
        navigator.clipboard.writeText(dossier.markdown_report).then(() => {
          alert('Markdown report copied to clipboard!');
        });
      }
    });

    container.querySelector('#btn-export-md')?.addEventListener('click', () => {
      if (dossier.markdown_report) {
        const blob = new Blob([dossier.markdown_report], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `research_report_${dossier.run_id}.md`;
        a.click();
        URL.revokeObjectURL(url);
      }
    });

    container.querySelector('#btn-export-json')?.addEventListener('click', () => {
      const blob = new Blob([JSON.stringify(dossier, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `research_dossier_${dossier.run_id}.json`;
      a.click();
      URL.revokeObjectURL(url);
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
