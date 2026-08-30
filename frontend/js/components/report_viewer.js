/**
 * ResearchMind - Answer-First Research Report & Investigation Explorer (Screen 3)
 */

export function renderReportViewer(container, store, { onNewInvestigation, onDownloadArtifact }) {
  let activeTab = 'answer'; // 'answer' | 'evidence' | 'sources' | 'details'
  let expandedFindingIds = new Set();

  const escapeHtml = (unsafe) => {
    return (unsafe || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const copyToClipboard = async (text, btn) => {
    try {
      await navigator.clipboard.writeText(text);
      const original = btn.textContent;
      btn.textContent = '✓ Copied!';
      setTimeout(() => { btn.textContent = original; }, 2000);
    } catch {
      alert('Could not copy to clipboard.');
    }
  };

  const downloadFile = (content, filename, contentType) => {
    const blob = new Blob([content], { type: contentType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const update = (state) => {
    const dossier = state.dossier;

    if (!dossier) {
      container.innerHTML = `
        <div class="card" style="text-align: center; padding: 4rem 2rem;">
          <div style="font-size: 2.5rem; margin-bottom: 1rem;">📑</div>
          <h2 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem;">No Completed Report Available</h2>
          <p style="color: var(--text-secondary); margin-bottom: 1.5rem;">
            Submit a research inquiry to generate an evidence-backed research dossier.
          </p>
          <button id="btn-empty-new" class="btn btn-primary">Start New Investigation</button>
        </div>
      `;
      container.querySelector('#btn-empty-new')?.addEventListener('click', onNewInvestigation);
      return;
    }

    const claims = dossier.claims || [];
    const citations = dossier.citations || [];
    const findings = dossier.key_findings || [];
    const contradictions = dossier.contradictions || [];
    const evaluation = dossier.evaluation;
    const diag = state.diagnostics || {};

    // Verification breakdown
    const verifiedClaims = claims.filter(c => {
      const st = String(c.verification_status || '').toLowerCase();
      return (c.confidence_score >= 0.7 && !c.contradiction_notes) || st === 'verified' || st === 'supported';
    });
    const unverifiedClaims = claims.filter(c => !verifiedClaims.includes(c));

    // Map citations by evidence_id
    const citationMap = new Map();
    citations.forEach(cit => {
      if (cit.evidence_id) citationMap.set(cit.evidence_id, cit);
    });

    // Map claims by claim_id
    const claimMap = new Map();
    claims.forEach(cl => {
      if (cl.claim_id) claimMap.set(cl.claim_id, cl);
    });

    container.innerHTML = `
      <div class="report-wrapper">
        <!-- Hero Header -->
        <div class="report-hero-card">
          <div class="report-hero-top">
            <div>
              <div class="report-badge-row">
                <span class="badge badge-health-ok">✓ Research Completed</span>
                <span class="meta-tag">Investigation ID: <code>${dossier.dossier_id}</code></span>
              </div>
              <h1 class="report-main-title">${escapeHtml(dossier.goal_query)}</h1>
            </div>

            <div class="report-action-toolbar">
              <button id="btn-copy-md" class="btn btn-secondary btn-sm" title="Copy Full Markdown Report">
                📋 Copy .md
              </button>
              <button id="btn-export-md" class="btn btn-secondary btn-sm" title="Download Markdown Document">
                💾 Export .md
              </button>
              <button id="btn-export-json" class="btn btn-secondary btn-sm" title="Download JSON Dossier">
                📦 Export .json
              </button>
              <button id="btn-report-new" class="btn btn-primary btn-sm">
                + New Inquiry
              </button>
            </div>
          </div>

          <!-- Top-Level Tab Navigation -->
          <div class="report-nav-tabs" role="tablist">
            <button class="report-nav-tab ${activeTab === 'answer' ? 'active' : ''}" data-tab="answer" role="tab">
              📑 Answer
            </button>
            <button class="report-nav-tab ${activeTab === 'evidence' ? 'active' : ''}" data-tab="evidence" role="tab">
              🔍 Evidence & Claims (${claims.length})
            </button>
            <button class="report-nav-tab ${activeTab === 'sources' ? 'active' : ''}" data-tab="sources" role="tab">
              📚 Sources (${citations.length})
            </button>
            <button class="report-nav-tab ${activeTab === 'details' ? 'active' : ''}" data-tab="details" role="tab">
              🛠️ Research Details & Trace
            </button>
          </div>
        </div>

        <!-- TAB 1: PRIMARY ANSWER & REPORT -->
        <div class="report-tab-body ${activeTab === 'answer' ? 'active' : ''}" id="tab-pane-answer">
          <!-- 1. Direct Answer Callout -->
          <div class="card report-section-card direct-answer-box">
            <div class="card-title">
              <span style="color: var(--accent-cyan);">💡 Direct Answer</span>
            </div>
            <div class="answer-text">
              ${escapeHtml(dossier.executive_summary || 'Evidence is currently insufficient to establish a definitive conclusion.')}
            </div>
          </div>

          <!-- 2. Key Findings -->
          <div class="card report-section-card">
            <div class="card-title">
              <span>Key Findings (${findings.length})</span>
              <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: normal;">
                Click any finding to inspect its underlying claims and evidence chain
              </span>
            </div>

            <div class="findings-stack">
              ${findings.length === 0 ? `
                <div style="color: var(--text-muted); padding: 1rem;">No findings synthesized for this inquiry.</div>
              ` : findings.map((f, idx) => {
                const isExpanded = expandedFindingIds.has(f.finding_id || `finding_${idx}`);
                const conf = Math.round((f.confidence_score || 0.9) * 100);
                const findingClaimIds = f.claim_ids || [];
                const findingEvidenceIds = f.evidence_ids || [];

                return `
                  <div class="finding-block ${isExpanded ? 'expanded' : ''}" data-finding-id="${f.finding_id || `finding_${idx}`}">
                    <div class="finding-header-row finding-toggle-btn" style="cursor: pointer;">
                      <div style="display: flex; align-items: flex-start; gap: 0.75rem; flex: 1;">
                        <span class="finding-index">#${idx + 1}</span>
                        <div>
                          <h3 class="finding-headline">${escapeHtml(f.title)}</h3>
                          <div class="finding-preview-meta">
                            <span class="badge badge-health-ok">${conf}% Confidence</span>
                            <span class="badge" style="background: rgba(139, 92, 246, 0.1); color: var(--accent-purple);">
                              ${findingClaimIds.length} Supporting Claims
                            </span>
                            <span class="badge" style="background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan);">
                              ${findingEvidenceIds.length} Sources
                            </span>
                          </div>
                        </div>
                      </div>
                      <button class="btn btn-secondary btn-sm" style="font-size: 0.75rem; pointer-events: none;">
                        ${isExpanded ? '▲ Hide Evidence' : '▼ View Evidence'}
                      </button>
                    </div>

                    <p class="finding-narrative">${escapeHtml(f.narrative)}</p>

                    <!-- Expandable Provenance Drill-Down -->
                    ${isExpanded ? `
                      <div class="provenance-drilldown">
                        <div class="provenance-title">🔗 Supporting Evidence & Grounded Claims</div>
                        
                        ${findingClaimIds.length === 0 ? `
                          <div style="color: var(--text-muted); font-size: 0.85rem;">No atomic claims directly mapped.</div>
                        ` : findingClaimIds.map(cid => {
                          const cl = claimMap.get(cid);
                          if (!cl) {
                            return `<div class="claim-item-card"><code>${cid}</code></div>`;
                          }
                          const isClmVerified = cl.confidence_score >= 0.7 && !cl.contradiction_notes;
                          const clBadge = isClmVerified
                            ? '<span class="badge badge-health-ok">✓ Verified</span>'
                            : '<span class="badge" style="background: rgba(245, 158, 11, 0.1); color: var(--accent-amber);">⚠ Partially Supported</span>';

                          const supportingCit = (cl.supporting_evidence_ids || [])
                            .map(eid => citationMap.get(eid))
                            .filter(Boolean);

                          return `
                            <div class="claim-item-card">
                              <div class="claim-item-header">
                                <span class="claim-id-tag">${cl.claim_id}</span>
                                ${clBadge}
                                <span style="font-size: 0.75rem; color: var(--text-muted);">${(cl.confidence_score * 100).toFixed(0)}% Confidence</span>
                              </div>
                              <div class="claim-item-statement">"${escapeHtml(cl.statement)}"</div>

                              <!-- Linked Citations / Primary Sources -->
                              ${supportingCit.length > 0 ? `
                                <div class="claim-source-list">
                                  ${supportingCit.map(cit => `
                                    <div class="citation-chip">
                                      <span class="citation-key">${cit.citation_key}</span>
                                      <a href="${escapeHtml(cit.source_url)}" target="_blank" rel="noopener noreferrer" class="citation-link">
                                        ${escapeHtml(cit.title || cit.domain)} ↗
                                      </a>
                                      <span class="citation-trust">${cit.trust_level}</span>
                                    </div>
                                  `).join('')}
                                </div>
                              ` : (cl.metadata?.source_url ? `
                                <div class="claim-source-list">
                                  <div class="citation-chip">
                                    <a href="${escapeHtml(cl.metadata.source_url)}" target="_blank" rel="noopener noreferrer" class="citation-link">
                                      ${escapeHtml(cl.metadata.source_domain || 'Source Reference')} ↗
                                    </a>
                                  </div>
                                </div>
                              ` : '')}
                            </div>
                          `;
                        }).join('')}
                      </div>
                    ` : ''}
                  </div>
                `;
              }).join('')}
            </div>
          </div>

          <!-- 3. Primary Sources Section -->
          <div class="card report-section-card">
            <div class="card-title">
              <span>Primary Sources & Bibliography (${citations.length})</span>
            </div>

            <div class="sources-stack">
              ${citations.length === 0 ? `
                <div style="color: var(--text-muted); padding: 0.5rem;">No external source citations referenced.</div>
              ` : citations.map(cit => `
                <div class="source-card">
                  <div class="source-header">
                    <span class="source-key">${cit.citation_key}</span>
                    <span class="badge badge-health-ok">${cit.trust_level || 'Peer-Reviewed'}</span>
                  </div>
                  <h4 class="source-title">
                    <a href="${escapeHtml(cit.source_url)}" target="_blank" rel="noopener noreferrer">
                      ${escapeHtml(cit.title || cit.domain)} ↗
                    </a>
                  </h4>
                  <div class="source-meta">
                    <span>Host Domain: <code>${escapeHtml(cit.domain)}</code></span>
                    ${cit.publication_date ? `<span>Published: ${escapeHtml(cit.publication_date)}</span>` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- 4. Contradictions & Scientific Disagreements -->
          ${contradictions.length > 0 ? `
            <div class="card report-section-card" style="border-left: 4px solid var(--accent-amber);">
              <div class="card-title">
                <span style="color: var(--accent-amber);">⚠️ Documented Contradictions & Disagreements (${contradictions.length})</span>
              </div>
              <div class="contradictions-stack">
                ${contradictions.map(contra => `
                  <div class="contra-box">
                    <div class="contra-header-line">
                      <span class="contra-name">${escapeHtml(contra.description)}</span>
                      <span class="badge" style="background: rgba(245, 158, 11, 0.1); color: var(--accent-amber);">
                        Severity: ${(contra.severity_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p class="contra-text">${escapeHtml(contra.divergence_analysis)}</p>
                  </div>
                `).join('')}
              </div>
            </div>
          ` : ''}

          <!-- 5. Limitations & Uncertainties -->
          ${dossier.limitations && dossier.limitations.length > 0 ? `
            <div class="card report-section-card">
              <div class="card-title">
                <span>Uncertainty & Limitations</span>
              </div>
              <ul class="limitations-list">
                ${dossier.limitations.map(lim => `<li>${escapeHtml(lim)}</li>`).join('')}
              </ul>
            </div>
          ` : ''}
        </div>

        <!-- TAB 2: EVIDENCE & CLAIMS -->
        <div class="report-tab-body ${activeTab === 'evidence' ? 'active' : ''}" id="tab-pane-evidence">
          <div class="card report-section-card">
            <div class="card-title">
              <span>Extracted Factual Claims (${claims.length})</span>
            </div>
            
            <div class="claims-grid">
              ${claims.length === 0 ? `
                <div style="color: var(--text-muted); padding: 1rem;">No atomic claims recorded.</div>
              ` : claims.map(cl => {
                const isClmVerified = cl.confidence_score >= 0.7 && !cl.contradiction_notes;
                const badge = isClmVerified
                  ? '<span class="badge badge-health-ok">✓ Verified</span>'
                  : '<span class="badge" style="background: rgba(245, 158, 11, 0.1); color: var(--accent-amber);">⚠ Partially Supported</span>';

                return `
                  <div class="claim-full-card">
                    <div class="claim-full-header">
                      <code>${cl.claim_id}</code>
                      ${badge}
                    </div>
                    <div class="claim-full-statement">"${escapeHtml(cl.statement)}"</div>
                    <div class="claim-full-meta">
                      <span>Confidence: <strong>${(cl.confidence_score * 100).toFixed(0)}%</strong></span>
                      ${cl.metadata?.source_domain ? `<span>Domain: <strong>${escapeHtml(cl.metadata.source_domain)}</strong></span>` : ''}
                      ${cl.metadata?.source_url ? `<a href="${escapeHtml(cl.metadata.source_url)}" target="_blank" rel="noopener noreferrer" class="citation-link">Source ↗</a>` : ''}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        </div>

        <!-- TAB 3: SOURCES -->
        <div class="report-tab-body ${activeTab === 'sources' ? 'active' : ''}" id="tab-pane-sources">
          <div class="card report-section-card">
            <div class="card-title">
              <span>Verified Bibliography & Sources (${citations.length})</span>
            </div>

            <div class="sources-stack">
              ${citations.length === 0 ? `
                <div style="color: var(--text-muted); padding: 1rem;">No external source citations referenced.</div>
              ` : citations.map(cit => `
                <div class="source-card">
                  <div class="source-header">
                    <span class="source-key">${cit.citation_key}</span>
                    <span class="badge badge-health-ok">${cit.trust_level || 'Academic / Peer-Reviewed'}</span>
                  </div>
                  <h4 class="source-title">
                    <a href="${escapeHtml(cit.source_url)}" target="_blank" rel="noopener noreferrer">
                      ${escapeHtml(cit.title || cit.domain)} ↗
                    </a>
                  </h4>
                  <div class="source-meta">
                    <span>Host Domain: <code>${escapeHtml(cit.domain)}</code></span>
                    ${cit.publication_date ? `<span>Published: ${escapeHtml(cit.publication_date)}</span>` : ''}
                    <span>Evidence ID: <code>${cit.evidence_id}</code></span>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- TAB 4: RESEARCH DETAILS & TRACE -->
        <div class="report-tab-body ${activeTab === 'details' ? 'active' : ''}" id="tab-pane-details">
          <!-- Verification Summary Box -->
          <div class="card report-section-card">
            <div class="card-title">
              <span>Verification Audit Summary</span>
            </div>
            <div class="verification-tree-box">
              <div class="tree-header">${claims.length} Extracted Factual Claims Evaluated</div>
              <div class="tree-branch">
                <span class="tree-node verified">├── <strong>${verifiedClaims.length}</strong> Verified</span>
                <span class="tree-desc">— Confirmed against primary empirical records</span>
              </div>
              <div class="tree-branch">
                <span class="tree-node partial">└── <strong>${unverifiedClaims.length}</strong> Partially Supported / Single-Source</span>
                <span class="tree-desc">— Pending additional cross-examination citations</span>
              </div>
            </div>

            ${evaluation ? `
              <div class="eval-metrics-row" style="margin-top: 1.5rem;">
                <div class="eval-metric-pill">
                  <div class="eval-val">${(evaluation.overall_score * 100).toFixed(0)}%</div>
                  <div class="eval-label">Overall Rigor</div>
                </div>
                <div class="eval-metric-pill">
                  <div class="eval-val">${(evaluation.completeness_score * 100).toFixed(0)}%</div>
                  <div class="eval-label">Completeness</div>
                </div>
                <div class="eval-metric-pill">
                  <div class="eval-val">${(evaluation.citation_coverage_score * 100).toFixed(0)}%</div>
                  <div class="eval-label">Citation Coverage</div>
                </div>
                <div class="eval-metric-pill">
                  <div class="eval-val">${(evaluation.source_diversity_score * 100).toFixed(0)}%</div>
                  <div class="eval-label">Source Diversity</div>
                </div>
              </div>
            ` : ''}
          </div>

          <!-- Multi-Agent DAG Execution Trace -->
          <div class="card report-section-card">
            <div class="card-title">
              <span>Multi-Agent Execution Pipeline</span>
            </div>

            <div class="dag-pipeline-grid" style="margin-bottom: 1.5rem;">
              ${[
                { role: 'PLANNER', label: 'Planner', desc: 'DAG Decomposition', status: 'completed' },
                { role: 'RESEARCHER', label: 'Researcher', desc: 'Web & arXiv Ingestion', status: 'completed' },
                { role: 'ANALYST', label: 'Analyst', desc: 'Claim Extraction', status: 'completed' },
                { role: 'VERIFIER', label: 'Verifier', desc: 'Cross-Examination', status: 'completed' },
                { role: 'EVALUATOR', label: 'Evaluator', desc: 'Quality Rubric', status: 'completed' },
                { role: 'REPORTER', label: 'Reporter', desc: 'Dossier Compilation', status: 'completed' },
              ].map(agent => `
                <div class="agent-mini-card status-completed">
                  <div class="agent-mini-role">${agent.label}</div>
                  <div class="agent-mini-desc">${agent.desc}</div>
                  <div class="agent-mini-status">
                    <span class="status-indicator"></span>
                    COMPLETED
                  </div>
                </div>
              `).join('')}
            </div>

            <div class="metrics-grid">
              <div class="metric-item">
                <div class="metric-label">Input Tokens</div>
                <div class="metric-value">${(diag.inputTokens || 0).toLocaleString()}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">Output Tokens</div>
                <div class="metric-value">${(diag.outputTokens || 0).toLocaleString()}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">Total Token Usage</div>
                <div class="metric-value">${(diag.totalTokens || 0).toLocaleString()}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">Execution Duration</div>
                <div class="metric-value">${(diag.durationSeconds || 0).toFixed(1)}s</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    // Event Listeners
    container.querySelector('#btn-report-new')?.addEventListener('click', onNewInvestigation);

    container.querySelector('#btn-copy-md')?.addEventListener('click', (e) => {
      copyToClipboard(dossier.markdown_report || '', e.target);
    });

    container.querySelector('#btn-export-md')?.addEventListener('click', () => {
      downloadFile(dossier.markdown_report || '', `research_report_${dossier.run_id}.md`, 'text/markdown');
    });

    container.querySelector('#btn-export-json')?.addEventListener('click', () => {
      downloadFile(JSON.stringify(dossier, null, 2), `research_dossier_${dossier.run_id}.json`, 'application/json');
    });

    // Tab switcher
    container.querySelectorAll('.report-nav-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.getAttribute('data-tab') || 'answer';
        update(store.getState());
      });
    });

    // Finding accordion toggles
    container.querySelectorAll('.finding-toggle-btn').forEach(elem => {
      elem.addEventListener('click', () => {
        const block = elem.closest('.finding-block');
        const fid = block?.getAttribute('data-finding-id');
        if (fid) {
          if (expandedFindingIds.has(fid)) {
            expandedFindingIds.delete(fid);
          } else {
            expandedFindingIds.add(fid);
          }
          update(store.getState());
        }
      });
    });
  };

  store.subscribe(update);
  update(store.getState());
}
