// 共有 AudioContext。最初のユーザー操作で作成・resume する(自動再生ポリシー対策)。
let ctx = null;

export function getAudioContext() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC({ latencyHint: 'interactive' });
  }
  return ctx;
}

// 通話が自然に終わったときの切断音(短い下降2音)。
export function playHangupTone(volume = 0.5) {
  try {
    const c = getAudioContext();
    const t0 = c.currentTime + 0.05;
    [[480, 0], [380, 0.22]].forEach(([f, dt]) => {
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0, t0 + dt);
      g.gain.linearRampToValueAtTime(0.15 * volume, t0 + dt + 0.02);
      g.gain.linearRampToValueAtTime(0, t0 + dt + 0.18);
      o.connect(g); g.connect(c.destination);
      o.start(t0 + dt); o.stop(t0 + dt + 0.2);
    });
  } catch (e) { /* ignore */ }
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
