/**
 * ResearchMind - Main Application Orchestrator (Phase 7.4 Hardened)
 */

import { ApiClient } from './api.js';
import { AppStore, TERMINAL_STAGES } from './state.js';
import { renderHeader } from './components/header.js';
import { renderInquiryForm } from './components/inquiry_form.js';
import { renderAgentDag } from './components/agent_dag.js';
import { renderEventLog } from './components/event_log.js';
import { renderDiagnostics } from './components/diagnostics.js';
import { renderDossierViewer } from './components/dossier_viewer.js';
import { renderArtifactExplorer } from './components/artifact_explorer.js';

document.addEventListener('DOMContentLoaded', () => {
  const store = new AppStore();
  const api = new ApiClient();
  let eventSubscriptionCloser = null;
  let statusPollInterval = null;

  // DOM Container Elements
  const headerEl = document.getElementById('header-container');
  const inquiryEl = document.getElementById('inquiry-container');
  const dagEl = document.getElementById('dag-container');
  const eventLogEl = document.getElementById('event-log-container');
  const diagnosticsEl = document.getElementById('diagnostics-container');
  const dossierEl = document.getElementById('dossier-container');
  const artifactsEl = document.getElementById('artifacts-container');
  
  // Modal Elements
  const modalEl = document.getElementById('settings-modal');
  const modalKeyInput = document.getElementById('modal-api-key');
  const modalRememberCb = document.getElementById('modal-remember-key');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnSaveKey = document.getElementById('btn-save-key');
  const btnClearKey = document.getElementById('btn-clear-key');

  // 1. Initialize Components
  renderHeader(headerEl, store, () => openSettingsModal());
  renderInquiryForm(inquiryEl, store, (payload) => handleRunSubmission(payload));
  renderAgentDag(dagEl, store, () => handleCancelRun());
  renderEventLog(eventLogEl, store);
  renderDiagnostics(diagnosticsEl, store);
  renderDossierViewer(dossierEl, store);
  renderArtifactExplorer(artifactsEl, store, (artId) => handleArtifactDownload(artId));

  // 2. Health Check Probe
  const checkHealth = async () => {
    try {
      const data = await api.getHealth();
      store.setState({ health: { status: data.status || 'ok', version: data.version || '0.1.0' } });
    } catch {
      store.setState({ health: { status: 'error', version: '0.1.0' } });
    }
  };
  checkHealth();
  setInterval(checkHealth, 30000);

  // 3. Settings Modal Management
  function openSettingsModal() {
    const { apiKey, rememberApiKey } = store.getState();
    if (modalKeyInput) modalKeyInput.value = apiKey || '';
    if (modalRememberCb) modalRememberCb.checked = rememberApiKey;
    modalEl?.classList.add('open');
    modalKeyInput?.focus();
  }

  function closeSettingsModal() {
    modalEl?.classList.remove('open');
  }

  btnCloseModal?.addEventListener('click', closeSettingsModal);
  modalEl?.addEventListener('click', (e) => {
    if (e.target === modalEl) closeSettingsModal();
  });

  btnSaveKey?.addEventListener('click', () => {
    store.setApiKey(modalKeyInput?.value, modalRememberCb?.checked);
    closeSettingsModal();
  });

  btnClearKey?.addEventListener('click', () => {
    if (modalKeyInput) modalKeyInput.value = '';
    store.setApiKey('', false);
    closeSettingsModal();
  });

  // Helper to cleanup active subscriptions
  function cleanupActiveStreams() {
    if (eventSubscriptionCloser) {
      eventSubscriptionCloser();
      eventSubscriptionCloser = null;
    }
    if (statusPollInterval) {
      clearInterval(statusPollInterval);
      statusPollInterval = null;
    }
  }

  // 4. Research Run Submission Workflow
  async function handleRunSubmission(payload) {
    cleanupActiveStreams();
    store.resetRun();
    store.setState({ isSubmitting: true, goalQuery: payload.query, error: null });

    const { apiKey } = store.getState();

    try {
      const summary = await api.createRun(payload, apiKey);
      const runId = summary.run_id;

      store.setState({
        currentRunId: runId,
        runStage: summary.status || 'QUEUED',
        isSubmitting: false,
        isStreaming: true,
      });

      // Start SSE Event Subscription with auto-reconnection
      eventSubscriptionCloser = api.subscribeEvents(runId, apiKey, {
        onEvent: (event) => {
          store.handleSseEvent(event);
        },
        onReconnecting: (attempt, delayMs) => {
          store.setState({ isReconnecting: true, reconnectAttempt: attempt });
        },
        onError: (err) => {
          console.warn('SSE Stream interrupted, relying on REST status polling:', err);
          store.setState({ isStreaming: false, isReconnecting: false });
        },
        onComplete: () => {
          store.setState({ isStreaming: false, isReconnecting: false });
        },
      });

      // Start periodic status sync for Dossier, Artifacts, and token telemetry
      const syncRunState = async () => {
        try {
          const detail = await api.getRun(runId, apiKey);
          if (detail) {
            const updates = {
              runStage: detail.status,
              dossier: detail.dossier || null,
              artifacts: detail.artifacts || [],
            };

            if (detail.total_token_usage) {
              const diag = store.getState().diagnostics;
              updates.diagnostics = {
                ...diag,
                totalTokens: detail.total_token_usage.total_tokens || diag.totalTokens,
                inputTokens: detail.total_token_usage.input_tokens || diag.inputTokens,
                outputTokens: detail.total_token_usage.output_tokens || diag.outputTokens,
                durationSeconds: detail.duration_seconds || diag.durationSeconds,
              };
            }

            store.setState(updates);

            if (TERMINAL_STAGES.includes(detail.status)) {
              cleanupActiveStreams();
            }
          }
        } catch (err) {
          console.warn('Status sync poll error:', err);
        }
      };

      // Initial sync and interval polling
      syncRunState();
      statusPollInterval = setInterval(syncRunState, 1500);

    } catch (err) {
      store.setState({
        isSubmitting: false,
        error: err.message || 'Failed to initiate research inquiry.',
      });
    }
  }

  // 5. Cooperative Cancellation
  async function handleCancelRun() {
    const { currentRunId, apiKey } = store.getState();
    if (!currentRunId) return;

    try {
      await api.cancelRun(currentRunId, apiKey);
      store.setState({ runStage: 'CANCELLED' });
      cleanupActiveStreams();
    } catch (err) {
      alert(`Cancellation failed: ${err.message}`);
    }
  }

  // 6. Artifact Direct Download
  async function handleArtifactDownload(artifactId) {
    const { currentRunId, apiKey, artifacts } = store.getState();
    if (!currentRunId || !artifactId) return;

    try {
      const { content, contentType } = await api.downloadArtifact(currentRunId, artifactId, apiKey);
      const art = (artifacts || []).find(a => a.artifact_id === artifactId);
      const filename = art ? (art.object_key.split('/').pop() || `${artifactId}.txt`) : `${artifactId}.txt`;

      const blob = new Blob([content], { type: contentType || 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Failed to download artifact: ${err.message}`);
    }
  }

  // 7. Check URL parameters for direct run inspection (?run_id=...)
  const params = new URLSearchParams(window.location.search);
  const initialRunId = params.get('run_id');
  if (initialRunId) {
    store.setState({ currentRunId: initialRunId, runStage: 'QUEUED' });
    const { apiKey } = store.getState();
    api.getRun(initialRunId, apiKey).then(detail => {
      if (detail) {
        store.setState({
          runStage: detail.status,
          goalQuery: detail.goal_query,
          dossier: detail.dossier || null,
          artifacts: detail.artifacts || [],
        });
      }
    }).catch(() => {});
  }
});
