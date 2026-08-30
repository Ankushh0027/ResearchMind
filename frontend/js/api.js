/**
 * ResearchMind - Type-Safe API Client & SSE Event Stream Manager
 *
 * Implements exact backend REST and SSE contracts with zero fabricated schemas.
 * Uses native fetch with ReadableStream for SSE to support Bearer token authentication headers.
 */

export class ApiClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  /**
   * Helper to build standard request headers
   */
  _buildHeaders(apiKey = '', extraHeaders = {}) {
    const headers = {
      'Accept': 'application/json',
      ...extraHeaders,
    };
    if (apiKey && apiKey.trim()) {
      headers['Authorization'] = `Bearer ${apiKey.trim()}`;
      headers['X-API-Key'] = apiKey.trim();
    }
    return headers;
  }

  /**
   * Safe JSON error handler
   */
  async _handleError(response) {
    let errorDetail = {
      status: response.status,
      error_code: `HTTP_${response.status}`,
      message: response.statusText || 'An unexpected error occurred',
    };

    try {
      const data = await response.json();
      if (data && typeof data === 'object') {
        errorDetail = {
          status: response.status,
          error_code: data.error_code || errorDetail.error_code,
          message: data.message || (typeof data.detail === 'string' ? data.detail : errorDetail.message),
          details: data.details || (typeof data.detail === 'object' ? data.detail : null),
        };
      }
    } catch {
      // Body not JSON
    }

    if (response.status === 401) {
      errorDetail.message = 'Authentication required. Please provide a valid API key in settings.';
    } else if (response.status === 413) {
      errorDetail.message = 'Request payload exceeds maximum allowed size (1 MiB).';
    } else if (response.status === 429) {
      const retryAfter = response.headers.get('Retry-After');
      errorDetail.message = `Rate limit exceeded. Try again in ${retryAfter || '60'} seconds.`;
    }

    const err = new Error(errorDetail.message);
    err.status = response.status;
    err.detail = errorDetail;
    throw err;
  }

  /**
   * GET /healthz - System health & readiness check (public)
   */
  async getHealth() {
    try {
      const response = await fetch(`${this.baseUrl}/healthz`, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) {
        await this._handleError(response);
      }
      return await response.json();
    } catch (err) {
      if (!err.status) {
        err.message = 'Cannot connect to ResearchMind API server.';
      }
      throw err;
    }
  }

  /**
   * POST /api/v1/runs - Submit a new research run
   */
  async createRun(payload, apiKey = '') {
    const response = await fetch(`${this.baseUrl}/api/v1/runs`, {
      method: 'POST',
      headers: this._buildHeaders(apiKey, { 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      await this._handleError(response);
    }
    return await response.json();
  }

  /**
   * GET /api/v1/runs/{run_id} - Fetch run details, status, and dossier
   */
  async getRun(runId, apiKey = '') {
    const response = await fetch(`${this.baseUrl}/api/v1/runs/${encodeURIComponent(runId)}`, {
      method: 'GET',
      headers: this._buildHeaders(apiKey),
    });

    if (!response.ok) {
      await this._handleError(response);
    }
    return await response.json();
  }

  /**
   * POST /api/v1/runs/{run_id}/cancel - Cancel an active research run
   */
  async cancelRun(runId, apiKey = '') {
    const response = await fetch(`${this.baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
      headers: this._buildHeaders(apiKey),
    });

    if (!response.ok) {
      await this._handleError(response);
    }
    return await response.json();
  }

  /**
   * GET /api/v1/runs/{run_id}/artifacts - List durable artifacts
   */
  async listArtifacts(runId, apiKey = '') {
    const response = await fetch(`${this.baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/artifacts`, {
      method: 'GET',
      headers: this._buildHeaders(apiKey),
    });

    if (!response.ok) {
      await this._handleError(response);
    }
    return await response.json();
  }

  /**
   * GET /api/v1/runs/{run_id}/artifacts/{artifact_id} - Download artifact content
   */
  async downloadArtifact(runId, artifactId, apiKey = '') {
    const response = await fetch(
      `${this.baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
      {
        method: 'GET',
        headers: this._buildHeaders(apiKey, { 'Accept': '*/*' }),
      }
    );

    if (!response.ok) {
      await this._handleError(response);
    }
    
    const contentType = response.headers.get('Content-Type') || '';
    const etag = response.headers.get('ETag') || '';
    const content = await response.text();
    return { content, contentType, etag };
  }

  /**
   * Stream live Server-Sent Events with Bearer header support & resilient line parsing
   */
  subscribeEvents(runId, apiKey = '', { onEvent, onError, onComplete, signal }) {
    let aborted = false;

    const parseAndDispatch = (rawChunk) => {
      const blocks = rawChunk.split('\n\n');
      for (const block of blocks) {
        if (!block.trim()) continue;

        let eventType = 'message';
        let dataString = '';

        const lines = block.split('\n');
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const val = line.slice(5).trim();
            dataString = dataString ? `${dataString}\n${val}` : val;
          }
        }

        if (dataString) {
          try {
            const parsedData = JSON.parse(dataString);
            onEvent({ event: eventType, data: parsedData });
          } catch {
            onEvent({ event: eventType, data: dataString });
          }
        }
      }
    };

    const startStream = async () => {
      try {
        const response = await fetch(
          `${this.baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/events`,
          {
            method: 'GET',
            headers: this._buildHeaders(apiKey, { 'Accept': 'text/event-stream' }),
            signal,
          }
        );

        if (!response.ok) {
          await this._handleError(response);
        }

        if (!response.body) {
          throw new Error('ReadableStream not supported by browser response.');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          // Process all complete chunks
          for (let i = 0; i < parts.length - 1; i++) {
            parseAndDispatch(parts[i]);
          }
          buffer = parts[parts.length - 1];
        }

        if (buffer.trim()) {
          parseAndDispatch(buffer);
        }

        if (onComplete) onComplete();
      } catch (err) {
        if (signal && signal.aborted) return;
        if (onError) onError(err);
      }
    };

    startStream();

    return () => {
      aborted = true;
    };
  }
}
