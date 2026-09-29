// チャンク音声の先読み・途切れない再生・波形描画。
import { api } from './api.js';
import { getAudioContext } from './audio.js';
import { config } from './config.js';

const GAP = 0.15; // チャンク間の小さな間(秒)

export class CallPlayer {
  constructor(sessionId, volume) {
    this.ctx = getAudioContext();
    this.sid = sessionId;
    this.gain = this.ctx.createGain();
    this.gain.gain.value = volume;
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.gain.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
    this.buffers = []; this.nextFetch = 0; this.target = 0;
    this.fetching = false; this.scheduled = 0; this.started = false;
    this.cursor = 0; this.total = 0; this.allDone = false; this.closed = false;
    this.sources = []; this.lastPlayingAt = 0;
    this.waitAfter = new Set(); this.hold = null; this.holdEnd = 0; this.waiting = false;
  }

  update(st) {
    this.target = st.chunks_ready || 0;
    this.total = st.chunks_total ?? this.target;
    this.allDone = !!st.all_done;
    this.waitAfter = new Set(config.reply_wait_enabled && Array.isArray(st.wait_after) ? st.wait_after : []);
    this._pump();
  }

  async _pump() {
    if (this.fetching || this.closed) return;
    this.fetching = true;
    try {
      while (!this.closed && this.nextFetch < this.target) {
        const i = this.nextFetch;
        const ab = await api.chunk(this.sid, i);
        const buf = await this.ctx.decodeAudioData(ab);
        if (this.closed) return;
        this.buffers[i] = buf;
        this.nextFetch = i + 1;
        if (this.started) this._schedule();
      }
    } catch (e) {
      // 次の status ポーリングで再試行
    } finally {
      this.fetching = false;
    }
  }

  start() {
    this.started = true;
    this.cursor = this.ctx.currentTime + 0.05;
    this.lastPlayingAt = performance.now();
    this._schedule();
  }

  _schedule() {
    while (this.hold === null && this.scheduled < this.buffers.length && this.buffers[this.scheduled]) {
      const buf = this.buffers[this.scheduled];
      const src = this.ctx.createBufferSource();
      src.buffer = buf; src.connect(this.gain);
      const at = Math.max(this.cursor, this.ctx.currentTime + 0.03);
      src.start(at);
      this.sources.push(src);
      this.cursor = at + buf.duration + GAP;
      const idx = this.scheduled++;
      // 返事待ちの位置: ここまでで予約を止める(先読み(_pump)は続く)
      if (this.waitAfter.has(idx) && !(this.allDone && idx >= this.total - 1)) {
        this.hold = idx; this.holdEnd = this.cursor - GAP;
      }
    }
  }

  // 返事待ち位置の再生が終わったか
  waitDue() { return this.hold !== null && !this.waiting && this.ctx.currentTime >= this.holdEnd; }
  get holding() { return this.hold !== null; }

  // 返事待ちを終えて続きを今の時刻から予約する
  resume() {
    if (this.hold === null || this.closed) return;
    this.waitAfter.delete(this.hold);
    this.hold = null; this.waiting = false;
    this.cursor = this.ctx.currentTime + 0.05;
    this._schedule();
  }

  get hasScheduled() { return this.scheduled > 0; }

  get playing() { return this.started && this.ctx.currentTime < this.cursor - GAP; }

  finished() {
    return this.started && this.allDone && this.scheduled >= this.total && this.scheduled > 0 && !this.playing;
  }

  // 再生が途切れて次のチャンクを待っている時間(ms)
  stalledMs() {
    if (!this.started || this.hold !== null) return 0;
    if (this.playing) { this.lastPlayingAt = performance.now(); return 0; }
    return performance.now() - this.lastPlayingAt;
  }

  stop() {
    this.closed = true;
    for (const s of this.sources) { try { s.stop(); } catch (e) {} try { s.disconnect(); } catch (e) {} }
    this.sources = [];
    try { this.gain.disconnect(); this.analyser.disconnect(); } catch (e) {}
  }
}

// 波形描画。analyser が null または synthetic 指定なら擬似波形。
export function startWave(canvas, getAnalyser) {
  const g = canvas.getContext('2d');
  let raf = 0, alive = true, phase = 0;
  const buf = new Uint8Array(1024);
  const draw = () => {
    if (!alive) return;
    const W = canvas.width, H = canvas.height, mid = H / 2;
    g.clearRect(0, 0, W, H);
    const an = getAnalyser();
    const bars = 48, bw = W / bars;
    let vals = new Array(bars).fill(0);
    if (an) {
      an.getByteTimeDomainData(buf);
      const step = Math.floor(buf.length / bars);
      for (let i = 0; i < bars; i++) {
        let m = 0;
        for (let j = 0; j < step; j++) m = Math.max(m, Math.abs(buf[i * step + j] - 128) / 128);
        vals[i] = Math.min(1, m * 2.2);
      }
    } else {
      phase += 0.12;
      for (let i = 0; i < bars; i++) {
        vals[i] = 0.25 + 0.2 * Math.sin(phase + i * 0.5) * Math.sin(phase * 0.7 + i * 0.13) + 0.1 * Math.random();
      }
    }
    const grad = g.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, '#7de3ff'); grad.addColorStop(1, '#b9a8ff');
    g.fillStyle = grad;
    for (let i = 0; i < bars; i++) {
      const h = Math.max(6, vals[i] * H * 0.9);
      const x = i * bw + bw * 0.2, w = bw * 0.6, r = w / 2;
      g.beginPath();
      g.roundRect ? g.roundRect(x, mid - h / 2, w, h, r) : g.rect(x, mid - h / 2, w, h);
      g.fill();
    }
    raf = requestAnimationFrame(draw);
  };
  draw();
  return () => { alive = false; cancelAnimationFrame(raf); };
}
