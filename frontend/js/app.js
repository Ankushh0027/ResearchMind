/**
 * ResearchMind - Application Orchestrator & Screen Switcher (Phase 7.5 Overhaul)
 */

import { ApiClient } from './api.js';
import { AppStore } from './state.js';
import { renderHeader } from './components/header.js';
import { renderInquiryForm } from './components/inquiry_form.js';
import { renderLiveInvestigation } from './components/live_investigation.js';
import { renderReportViewer } from './components/report_viewer.js';

document.addEventListener('DOMContentLoaded', () => {
  const store = new AppStore();
  const api = new ApiClient();
  let eventSubscriptionCloser = null;
  let statusPollInterval = null;

  // Top-Level DOM Containers
  const headerEl = document.getElementById('header-container');
  const screenInputEl = document.getElementById('screen-input');
  const screenInvestigatingEl = document.getElementById('screen-investigating');
  const screenReportEl = document.getElementById('screen-report');

  // Modal Elements
  const modalEl = document.getElementById('settings-modal');
  const modalKeyInput = document.getElementById('modal-api-key');
  const modalRememberCb = document.getElementById('modal-remember-key');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnSaveKey = document.getElementById('btn-save-key');
  const btnClearKey = document.getElementById('btn-clear-key');

  // 1. Initialize Components
  renderHeader(headerEl, store, {
    onOpenSettings: () => openSettingsModal(),
    onNewInvestigation: () => handleNewInvestigation(),
  });

  renderInquiryForm(screenInputEl, store, (payload) => handleRunSubmission(payload));

  renderLiveInvestigation(screenInvestigatingEl, store, {
    onCancel: () => handleCancelRun(),
    onReset: () => handleNewInvestigation(),
  });

  renderReportViewer(screenReportEl, store, {
    onNewInvestigation: () => handleNewInvestigation(),
    onDownloadArtifact: (artId) => handleArtifactDownload(artId),
  });

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

  // 3. Screen Visibility State Machine
  const updateScreenVisibility = (state) => {
    const stage = state.runStage;

    if (stage === 'COMPLETED' && state.dossier) {
      // Screen 3: Final Report
      screenInputEl.style.display = 'none';
      screenInvestigatingEl.style.display = 'none';
      screenReportEl.style.display = 'block';
    } else if (['SUBMITTING', 'QUEUED', 'PLANNING', 'RESEARCHING', 'ANALYZING', 'VERIFYING', 'EVALUATING', 'REPORTING', 'RECONNECTING', 'FAILED', 'CANCELLED'].includes(stage)) {
      // Screen 2: Live Investigation
      screenInputEl.style.display = 'none';
      screenInvestigatingEl.style.display = 'block';
      screenReportEl.style.display = 'none';
    } else {
      // Screen 1: Clean Input Landing
      screenInputEl.style.display = 'block';
      screenInvestigatingEl.style.display = 'none';
      screenReportEl.style.display = 'none';
    }
  };

  store.subscribe(updateScreenVisibility);
  updateScreenVisibility(store.getState());

  // 4. Settings Modal Management
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

  function handleNewInvestigation() {
    cleanupActiveStreams();
    store.resetRun();
    // Clear URL query param if present
    if (window.history && window.history.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.delete('run_id');
      window.history.replaceState({}, '', url.toString());
    }
  }

  // 5. Research Run Submission Workflow
  async function handleRunSubmission(payload) {
    cleanupActiveStreams();
    store.resetRun();
    store.setState({ isSubmitting: true, goalQuery: payload.query, error: null, runStage: 'SUBMITTING' });

    const { apiKey } = store.getState();

    try {
      const summary = await api.createRun(payload, apiKey);
      const runId = summary.run_id;

      // Update URL with run_id
      if (window.history && window.history.replaceState) {
        const url = new URL(window.location.href);
        url.searchParams.set('run_id', runId);
        window.history.replaceState({}, '', url.toString());
      }

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
        onReconnecting: (attempt) => {
          store.setState({ isReconnecting: true, reconnectAttempt: attempt });
        },
        onError: (err) => {
          console.warn('SSE stream interrupted, falling back to REST status polling:', err);
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
                inputTokens: detail.total_token_usage.prompt_tokens || diag.inputTokens,
                outputTokens: detail.total_token_usage.completion_tokens || diag.outputTokens,
                durationSeconds: detail.duration_seconds || diag.durationSeconds,
                totalTasks: (detail.completed_task_ids?.length || 0) + (detail.failed_task_ids?.length || 0),
                completedTasks: detail.completed_task_ids?.length || 0,
                failedTasks: detail.failed_task_ids?.length || 0,
                claimsCount: detail.dossier?.claims?.length || diag.claimsCount,
              };
            }

            if (detail.error) {
              updates.error = detail.error;
            }

            store.setState(updates);

            // If terminal state reached, cleanup polling & SSE
            if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(detail.status)) {
              cleanupActiveStreams();
            }
          }
        } catch (pollErr) {
          console.warn('Status poll error:', pollErr);
        }
      };

      // Poll every 1.5s while active
      statusPollInterval = setInterval(syncRunState, 1500);
      syncRunState();

    } catch (err) {
      console.error('Submission failed:', err);
      store.setState({
        isSubmitting: false,
        runStage: 'FAILED',
        error: err.message || 'Failed to submit research inquiry',
      });
    }
  }

  // 6. Cooperative Run Cancellation
  async function handleCancelRun() {
    const { currentRunId, apiKey } = store.getState();
    if (!currentRunId) return;

    try {
      await api.cancelRun(currentRunId, apiKey);
      store.setState({ runStage: 'CANCELLED' });
      cleanupActiveStreams();
    } catch (err) {
      console.error('Cancellation request failed:', err);
      store.setState({ error: err.message || 'Failed to cancel research run' });
    }
  }

  // 7. Artifact Download
  async function handleArtifactDownload(artifactId) {
    const { currentRunId, apiKey } = store.getState();
    if (!currentRunId || !artifactId) return;

    try {
      const { content, contentType } = await api.downloadArtifact(currentRunId, artifactId, apiKey);
      const blob = new Blob([content], { type: contentType || 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `artifact_${artifactId}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Download artifact failed:', err);
      alert(`Could not download artifact: ${err.message}`);
    }
  }

  // 8. Auto-load run_id from URL query if present
  const urlParams = new URLSearchParams(window.location.search);
  const initialRunId = urlParams.get('run_id');
  if (initialRunId && initialRunId.trim()) {
    const cleanId = initialRunId.trim();
    store.setState({ currentRunId: cleanId, runStage: 'SUBMITTING' });
    const { apiKey } = store.getState();
    api.getRun(cleanId, apiKey).then(detail => {
      if (detail) {
        store.setState({
          goalQuery: detail.goal_query,
          runStage: detail.status,
          dossier: detail.dossier || null,
          artifacts: detail.artifacts || [],
          error: detail.error || null,
        });
      }
    }).catch(err => {
      console.warn('Initial run lookup failed:', err);
      store.resetRun();
    });
  }
});
