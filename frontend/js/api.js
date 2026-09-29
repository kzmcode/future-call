// バックエンド API ラッパー。失敗時は status 付きの Error を投げる。
const T0 = performance.now();

async function req(path, opts = {}, timeoutMs = 15000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch('/api' + path, { ...opts, signal: ctl.signal, cache: 'no-store' });
    if (!res.ok) {
      const e = new Error('HTTP ' + res.status);
      e.status = res.status;
      throw e;
    }
    return res;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  async health() { return (await req('/health', {}, 4000)).json(); },
  async config() { return (await req('/config', {}, 4000)).json(); },
  async createSession() { return (await req('/sessions', { method: 'POST' })).json(); },
  async uploadRecording(id, blob, durationSec) {
    const fd = new FormData();
    fd.append('audio', blob, 'recording.wav');
    fd.append('duration_sec', String(durationSec));
    return (await req(`/sessions/${encodeURIComponent(id)}/recording`, { method: 'POST', body: fd }, 90000)).json();
  },
  async status(id) { return (await req(`/sessions/${encodeURIComponent(id)}/status`, {}, 8000)).json(); },
  async chunk(id, i) { return (await req(`/sessions/${encodeURIComponent(id)}/chunks/${i}`, {}, 30000)).arrayBuffer(); },
  async deleteSession(id) { await req(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }, 8000); },
  async reset() { await req('/reset', { method: 'POST' }, 8000); },
};

const EVENTS = new Set(['record_start', 'record_submit', 'ring_start', 'answer', 'call_end', 'missed_call', 'staff_reset', 'client_error']);

// fire-and-forget。内容は送らない。
export function log(event, ms) {
  if (!EVENTS.has(event)) return;
  try {
    fetch('/api/client-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event, ms: Math.round(ms ?? performance.now() - T0) }),
      keepalive: true,
    }).catch(() => {});
  } catch (e) { /* ignore */ }
}
