/**
 * ResearchMind - Reactive Deterministic State Store
 */

export class AppStore {
  constructor() {
    this._listeners = new Set();
    this._state = {
      health: { status: 'checking', version: '0.1.0' },
      apiKey: sessionStorage.getItem('rm_api_key') || '',
      rememberApiKey: Boolean(sessionStorage.getItem('rm_api_key')),
      tenantId: 'default-tenant',
      
      // Active run execution state
      currentRunId: null,
      goalQuery: '',
      runStage: 'IDLE', // IDLE, QUEUED, PLANNING, RESEARCHING, ANALYZING, VERIFYING, EVALUATING, REPORTING, COMPLETED, FAILED, CANCELLED
      isSubmitting: false,
      isStreaming: false,
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

      // Live event timeline logs
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
    this.setState({
      currentRunId: null,
      goalQuery: '',
      runStage: 'IDLE',
      isSubmitting: false,
      isStreaming: false,
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
   * Process actual backend SSE lifecycle events
   */
  handleSseEvent(rawEvent) {
    const { event, data } = rawEvent;
    const currentEvents = [...this._state.events, { ...rawEvent, timestamp: new Date().toLocaleTimeString() }];
    const nextStages = { ...this._state.agentStages };
    const nextDiag = { ...this._state.diagnostics };
    let nextRunStage = this._state.runStage;

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
        nextRunStage = 'PLANNING';
        nextStages.PLANNER = 'running';
        if (data.total_tasks) nextDiag.totalTasks = data.total_tasks;
        break;

      case 'TaskScheduledEvent':
        if (data.assigned_role && nextStages[data.assigned_role]) {
          if (nextStages[data.assigned_role] === 'idle') {
            nextStages[data.assigned_role] = 'queued';
          }
        }
        break;

      case 'TaskStartedEvent':
        if (data.subtask_id) {
          // Determine active stage based on subtask naming or role
          const lower = data.subtask_id.toLowerCase();
          if (lower.includes('research')) {
            nextStages.RESEARCHER = 'running';
            nextRunStage = 'RESEARCHING';
          } else if (lower.includes('anal')) {
            nextStages.ANALYST = 'running';
            nextRunStage = 'ANALYZING';
          } else if (lower.includes('verif')) {
            nextStages.VERIFIER = 'running';
            nextRunStage = 'VERIFYING';
          } else if (lower.includes('eval')) {
            nextStages.EVALUATOR = 'running';
            nextRunStage = 'EVALUATING';
          } else if (lower.includes('report')) {
            nextStages.REPORTER = 'running';
            nextRunStage = 'REPORTING';
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
    });
  }
}
