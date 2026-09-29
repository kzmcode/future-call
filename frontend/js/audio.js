// 共有 AudioContext。最初のユーザー操作で作成・resume する(自動再生ポリシー対策)。
let ctx = null;

export function getAudioContext() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC({ latencyHint: 'interactive' });
  }
  return ctx;
}

export async function unlockAudio() {
  try {
    const c = getAudioContext();
    if (c.state !== 'running') await c.resume();
    const b = c.createBuffer(1, 1, c.sampleRate);
    const s = c.createBufferSource();
    s.buffer = b; s.connect(c.destination); s.start(0);
  } catch (e) { /* ignore */ }
  try { // speechSynthesis もジェスチャ内で一度触れておく
    if ('speechSynthesis' in window) { speechSynthesis.getVoices(); }
  } catch (e) { /* ignore */ }
}
