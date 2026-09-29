// オリジナル着信音(Web Audio で合成)。中音域(1〜3kHz)中心のチャイム風メロディをループ。
import { getAudioContext } from './audio.js';

const N = { G6: 1568, A6: 1760, C7: 2093, D7: 2349, E7: 2637, E6: 1319 };
// [周波数, 開始(秒), 長さ(秒)]
const PHRASE = [
  [N.E6, 0.00, 0.16], [N.G6, 0.18, 0.16], [N.C7, 0.36, 0.16], [N.E7, 0.54, 0.30],
  [N.D7, 0.96, 0.16], [N.C7, 1.14, 0.16], [N.A6, 1.32, 0.16], [N.G6, 1.50, 0.34],
  [N.E6, 1.90, 0.16], [N.G6, 2.08, 0.16], [N.C7, 2.26, 0.16], [N.E7, 2.44, 0.45],
];
const CYCLE = 4.2;

export class Ringtone {
  constructor(volume) {
    this.volume = Math.max(0, Math.min(1, volume));
    this.master = null; this.timer = null; this.running = false;
  }

  start() {
    if (this.running) return;
    const ctx = getAudioContext();
    this.running = true;
    this.master = ctx.createGain();
    this.master.gain.value = this.volume * 0.45;
    this.master.connect(ctx.destination);
    const loop = () => {
      if (!this.running) return;
      this._cycle(ctx, ctx.currentTime + 0.05);
      this.timer = setTimeout(loop, CYCLE * 1000);
    };
    loop();
  }

  _cycle(ctx, t0) {
    for (const [f, s, d] of PHRASE) {
      const t = t0 + s;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(1, t + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t + d + 0.35);
      g.connect(this.master);
      const o1 = ctx.createOscillator(); o1.type = 'sine'; o1.frequency.value = f;
      const o2 = ctx.createOscillator(); o2.type = 'triangle'; o2.frequency.value = f * 1.002;
      const g2 = ctx.createGain(); g2.gain.value = 0.3;
      o1.connect(g); o2.connect(g2); g2.connect(g);
      o1.start(t); o2.start(t); o1.stop(t + d + 0.4); o2.stop(t + d + 0.4);
    }
  }

  stop() {
    this.running = false;
    clearTimeout(this.timer);
    const m = this.master; this.master = null;
    if (m) {
      try {
        const ctx = getAudioContext();
        m.gain.cancelScheduledValues(ctx.currentTime);
        m.gain.setTargetAtTime(0, ctx.currentTime, 0.02);
      } catch (e) {}
      setTimeout(() => { try { m.disconnect(); } catch (e) {} }, 400);
    }
  }
}
