/**
 * ResearchMind - Reactive Deterministic State Store (Phase 7.4 Hardened)
 *
 * Implements strict state machine transitions, event deduplication, and bounded memory buffers.
 */

export const TERMINAL_STAGES = Object.freeze(['COMPLETED', 'FAILED', 'CANCELLED']);

export class AppStore {
  constructor() {
    this._listeners = new Set();
    this._seenEventIds = new Set();
    this._maxEvents = 200;

    this._state = {
      health: { status: 'checking', version: '0.1.0' },
      apiKey: sessionStorage.getItem('rm_api_key') || '',
      rememberApiKey: Boolean(sessionStorage.getItem('rm_api_key')),
      tenantId: 'default-tenant',
      
      // Active run execution state
      currentRunId: null,
      goalQuery: '',
      runStage: 'IDLE', // IDLE, SUBMITTING, QUEUED, PLANNING, RESEARCHING, ANALYZING, VERIFYING, EVALUATING, REPORTING, COMPLETED, FAILED, CANCELLED, RECONNECTING
      isSubmitting: false,
      isStreaming: false,
      isReconnecting: false,
      reconnectAttempt: 0,
      error: null,

      // Live multi-agent DAG pipeline status
      agentStages: {
        PLANNER: 'idle',
        RESEARCHER: 'idle',
        ANALYST: 'idle',
        VERIFIER: 'idle',
        EVALUATOR: 'idle',
        REPORTER: 'idle',
      },

      // Diagnostics & Metrics
      diagnostics: {
        totalTokens: 0,
        inputTokens: 0,
        outputTokens: 0,
        durationSeconds: 0,
        overallScore: null,
        totalTasks: 0,
        completedTasks: 0,
        failedTasks: 0,
        claimsCount: 0,
        contradictionsCount: 0,
      },

      // Live event timeline logs (capped at _maxEvents)
      events: [],

      // Final compiled deliverable
      dossier: null,

      // Persistent artifacts
      artifacts: [],
    };
  }

  getState() {
    return this._state;
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  setState(updates) {
    // Guard: Do not overwrite terminal runStage with non-terminal stages
    if (
      updates.runStage &&
      TERMINAL_STAGES.includes(this._state.runStage) &&
      !TERMINAL_STAGES.includes(updates.runStage) &&
      updates.runStage !== 'IDLE' // allow reset to IDLE
    ) {
      delete updates.runStage;
    }

    this._state = { ...this._state, ...updates };
    for (const listener of this._listeners) {
      try {
        listener(this._state);
      } catch (err) {
        console.error('Error in state subscriber:', err);
      }
    }
  }

  setApiKey(key, remember = false) {
    const cleanKey = (key || '').trim();
    if (remember && cleanKey) {
      sessionStorage.setItem('rm_api_key', cleanKey);
    } else {
      sessionStorage.removeItem('rm_api_key');
    }
    this.setState({ apiKey: cleanKey, rememberApiKey: remember });
  }

  getMaskedApiKey() {
    const key = this._state.apiKey;
    if (!key) return 'None (Unauthenticated)';
    if (key.length <= 8) return '••••••••';
    return `${key.slice(0, 4)}••••${key.slice(-4)}`;
  }

  resetRun() {
    this._seenEventIds.clear();
    this.setState({
      currentRunId: null,
      goalQuery: '',
      runStage: 'IDLE',
      isSubmitting: false,
      isStreaming: false,
      isReconnecting: false,
      reconnectAttempt: 0,
      error: null,
      agentStages: {
        PLANNER: 'idle',
        RESEARCHER: 'idle',
        ANALYST: 'idle',
        VERIFIER: 'idle',
        EVALUATOR: 'idle',
        REPORTER: 'idle',
      },
      diagnostics: {
        totalTokens: 0,
        inputTokens: 0,
        outputTokens: 0,
        durationSeconds: 0,
        overallScore: null,
        totalTasks: 0,
        completedTasks: 0,
        failedTasks: 0,
        claimsCount: 0,
        contradictionsCount: 0,
      },
      events: [],
      dossier: null,
      artifacts: [],
    });
  }

  /**
   * Process actual backend SSE lifecycle events with deduplication and state machine guards
   */
  handleSseEvent(rawEvent) {
    const { event, data } = rawEvent;

    // Deduplication check based on event_id if present
    if (data && typeof data === 'object' && data.event_id) {
      if (this._seenEventIds.has(data.event_id)) {
        return; // Skip duplicate event
      }
      this._seenEventIds.add(data.event_id);
      if (this._seenEventIds.size > 1000) {
        // Prune older event IDs to bound set size
        const first = this._seenEventIds.values().next().value;
        this._seenEventIds.delete(first);
      }
    }

    // Append to events buffer (capped at _maxEvents)
    const newEntry = { ...rawEvent, timestamp: new Date().toLocaleTimeString() };
    const currentEvents = [...this._state.events, newEntry].slice(-this._maxEvents);

    const nextStages = { ...this._state.agentStages };
    const nextDiag = { ...this._state.diagnostics };
    let nextRunStage = this._state.runStage;

    // Do not alter terminal stage
    const isAlreadyTerminal = TERMINAL_STAGES.includes(this._state.runStage);

    if (data && typeof data === 'object') {
      if (data.token_usage) {
        nextDiag.totalTokens = data.token_usage.total_tokens || nextDiag.totalTokens;
        nextDiag.inputTokens = data.token_usage.input_tokens || nextDiag.inputTokens;
        nextDiag.outputTokens = data.token_usage.output_tokens || nextDiag.outputTokens;
      }
      if (typeof data.duration_seconds === 'number') {
        nextDiag.durationSeconds = data.duration_seconds;
      }
    }

    switch (event) {
      case 'RunStartedEvent':
        if (!isAlreadyTerminal) {
          nextRunStage = 'PLANNING';
          nextStages.PLANNER = 'running';
        }
        if (data.total_tasks) nextDiag.totalTasks = data.total_tasks;
        break;

      case 'TaskScheduledEvent':
        if (data.assigned_role && nextStages[data.assigned_role] !== undefined) {
          if (nextStages[data.assigned_role] === 'idle') {
            nextStages[data.assigned_role] = 'queued';
          }
        }
        break;

      case 'TaskStartedEvent':
        if (data.subtask_id) {
          const lower = data.subtask_id.toLowerCase();
          if (lower.includes('research')) {
            nextStages.RESEARCHER = 'running';
            if (!isAlreadyTerminal) nextRunStage = 'RESEARCHING';
          } else if (lower.includes('anal')) {
            nextStages.ANALYST = 'running';
            if (!isAlreadyTerminal) nextRunStage = 'ANALYZING';
          } else if (lower.includes('verif')) {
            nextStages.VERIFIER = 'running';
            if (!isAlreadyTerminal) nextRunStage = 'VERIFYING';
          } else if (lower.includes('eval')) {
            nextStages.EVALUATOR = 'running';
            if (!isAlreadyTerminal) nextRunStage = 'EVALUATING';
          } else if (lower.includes('report')) {
            nextStages.REPORTER = 'running';
            if (!isAlreadyTerminal) nextRunStage = 'REPORTING';
          }
        }
        break;

      case 'TaskCompletedEvent':
        nextDiag.completedTasks += 1;
        if (data.subtask_id) {
          const lower = data.subtask_id.toLowerCase();
          if (lower.includes('plan')) nextStages.PLANNER = 'completed';
          if (lower.includes('research')) nextStages.RESEARCHER = 'completed';
          if (lower.includes('anal')) nextStages.ANALYST = 'completed';
          if (lower.includes('verif')) nextStages.VERIFIER = 'completed';
          if (lower.includes('eval')) nextStages.EVALUATOR = 'completed';
          if (lower.includes('report')) nextStages.REPORTER = 'completed';
        }
        break;

      case 'TaskFailedEvent':
        nextDiag.failedTasks += 1;
        break;

      case 'RunCompletedEvent':
        nextRunStage = 'COMPLETED';
        Object.keys(nextStages).forEach(role => {
          if (nextStages[role] !== 'failed') nextStages[role] = 'completed';
        });
        break;

      case 'RunFailedEvent':
        nextRunStage = 'FAILED';
        break;

      case 'RunCancelledEvent':
        nextRunStage = 'CANCELLED';
        break;
    }

    this.setState({
      events: currentEvents,
      agentStages: nextStages,
      diagnostics: nextDiag,
      runStage: nextRunStage,
      isReconnecting: false,
    });
  }
}
