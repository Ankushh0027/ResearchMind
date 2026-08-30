/**
 * ResearchMind - Real-Time Event Log Console Component
 */

export function renderEventLog(container, store) {
  const update = (state) => {
    container.innerHTML = `
      <div class="card" style="height: 100%;">
        <div class="card-title">
          <span>📜 Real-Time Execution Timeline</span>
          <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">
            ${state.events.length} event(s)
          </span>
        </div>

        <div class="terminal-box" id="event-stream-box">
          ${state.events.length === 0 ? `
            <div style="color: var(--text-muted); padding: 1rem; text-align: center;">
              Waiting for inquiry execution to begin...
            </div>
          ` : state.events.map(e => {
            const dataStr = (typeof e.data === 'object' && e.data !== null)
              ? (e.data.output_summary || e.data.subtask_id || e.data.error_message || JSON.stringify(e.data))
              : String(e.data);

            return `
              <div class="log-entry">
                <span class="log-time">${e.timestamp}</span>
                <span class="log-type">${e.event}</span>
                <span class="log-msg">${escapeHtml(dataStr)}</span>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    // Auto-scroll to bottom
    const box = container.querySelector('#event-stream-box');
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
  };

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  store.subscribe(update);
  update(store.getState());
}
